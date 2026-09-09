import http.client
import json
import os
from pathlib import Path
import re
import threading
from unittest.mock import patch

import pytest

from memory_hub.app import running_instance, run
from memory_hub.dashboard import (DEFAULT_DASHBOARD_PORT, create_server, default_dashboard_host,
                                  default_dashboard_port, memory_rows_for_dashboard, load_html)
from memory_hub.dashboard_data import detail, metadata, save_metadata
from memory_hub.manager import MemoryManager
from memory_hub.models import MemoryRecord


@pytest.fixture
def manager(tmp_path):
    value = MemoryManager(tmp_path / "vault")
    value.initialize(Path(__file__).resolve().parents[1] / "vault_template")
    yield value
    value.close()


def session(manager):
    result = manager.propose_session(dict(
        model="claude", title="Readable session", project=None,
        investigated=["Read the canonical file", "Checked every section"],
        learned=["Structure matters"], completed=["Preserved line breaks"],
        next_steps=["Verify lookup editing"]), write_mode="auto")
    return result["memory"]["memory_id"]


def test_detail_preserves_sections_and_source(manager):
    memory_id = session(manager)
    row = detail(manager, memory_id)
    assert row["title"] == "Readable session"
    assert "### Investigated\n- Read the canonical file\n- Checked every section" in row["display"]
    assert "### Next Steps\n- Verify lookup editing" in row["source"]
    assert "claude" in row["source_tags"]


def test_metadata_survives_reindex_and_keeps_source(manager):
    first = session(manager)
    other = manager.propose_session(dict(model="demo", title="Another session", project=None,
        investigated=["Another investigation"], learned=[], completed=[], next_steps=[]),
        write_mode="auto")["memory"]["memory_id"]
    before = detail(manager, first)
    result = save_metadata(manager, first, dict(tags=["work", "work"], links=[other],
        revision=before["metadata_revision"]))
    assert result["status"] == "updated"
    assert detail(manager, first)["source"] == before["source"]
    assert detail(manager, other)["backlinks"] == [first]
    manager.reindex()
    assert detail(manager, first)["tags"] == ["work"]
    assert detail(manager, first)["links"] == [other]
    assert len(manager.index.all_rows()) == 2
    stale = save_metadata(manager, first, dict(tags=[], links=[], revision=before["metadata_revision"]))
    assert stale["status"] == "conflict"
    assert detail(manager, first)["tags"] == ["work"]


@pytest.mark.parametrize("tags,links", [(["bad tag"], []), ("not a list", []),
    ([], ["missing-id"]), (["x" * 65], []), ([3], []), ([], [4])])
def test_metadata_rejects_invalid_input(manager, tags, links):
    memory_id = session(manager)
    with pytest.raises(ValueError):
        save_metadata(manager, memory_id, dict(tags=tags, links=links,
            revision=detail(manager, memory_id)["metadata_revision"]))
    assert metadata(manager) == {}


def test_metadata_refuses_malformed_file(manager):
    from memory_hub.utils import atomic_write
    memory_id = session(manager)
    atomic_write(manager.vault.resolve("/dashboard-metadata.md"), "Damaged user file\n")
    with pytest.raises(ValueError, match="malformed"):
        detail(manager, memory_id)
    assert manager.vault.read("/dashboard-metadata.md") == "Damaged user file\n"


def test_library_has_no_200_or_search_50_cap(manager):
    for n in range(215):
        manager.index.upsert(MemoryRecord(str(n), "/demo.md", f"Needle {n}",
            "topic", "stated", "demo", "user", "2026-09-07"))
    assert len(memory_rows_for_dashboard(manager)) == 215
    assert len(memory_rows_for_dashboard(manager, "Needle")) == 215


def test_shared_server_security_metadata_and_reopen(manager):
    memory_id = session(manager)
    server = create_server(manager, port=0)
    other = create_server(manager, port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    port = server.server_address[1]
    def request(method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", port)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        value = response.read()
        connection.close()
        return response.status, value
    try:
        assert server.RequestHandlerClass.launch_token != other.RequestHandlerClass.launch_token
        assert request("GET", "/")[0] == 200
        assert request("GET", "/", headers={"Host": "attacker.invalid"})[0] == 403
        assert running_instance(manager.vault.root, port)
        assert not running_instance(manager.vault.root / "different", port)
        health_status, health_body = request("GET", "/api/worker-health")
        assert health_status == 200
        assert json.loads(health_body)["status"] in {"not_configured", "ok", "stopped", "degraded"}
        with patch("memory_hub.app.MemoryManager") as constructor, patch("memory_hub.app.webbrowser.open") as opened:
            run(manager.vault.root, port)
            constructor.assert_not_called()
            opened.assert_called_once()
        path = f"/api/memory/{memory_id}/metadata"
        body = json.dumps(dict(tags=["tested"], links=[], revision=detail(manager, memory_id)["metadata_revision"]))
        headers = {"X-Launch-Token": server.RequestHandlerClass.launch_token}
        assert request("POST", path, body)[0] == 403
        assert request("POST", path, body, headers | {"Origin": "https://localhost:" + str(port)})[0] == 403
        assert request("POST", path, body, headers)[0] == 200
        assert request("POST", path, body, headers)[0] == 409
        assert request("POST", path, "[]", headers)[0] == 400
        assert request("GET", "/api/memory/missing")[0] == 404
        assert request("POST", path, "", headers | {"Content-Length": "70000"})[0] == 400
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
        other.server_close()


def test_disallow_non_loopback(manager):
    with pytest.raises(ValueError):
        create_server(manager, "0.0.0.0", 0)


def test_dashboard_port_and_host_are_environment_driven():
    """#81: the port/host were hardcoded independently in six places; changing one
    without the others left app.py's single-instance probe checking the wrong port.
    One MEMORY_DASHBOARD_PORT/HOST pair must now drive every call site.
    """
    with patch.dict("os.environ", {}, clear=False):
        for key in ("MEMORY_DASHBOARD_PORT", "MEMORY_DASHBOARD_HOST"):
            os.environ.pop(key, None)
        assert default_dashboard_port() == DEFAULT_DASHBOARD_PORT == 8765
        assert default_dashboard_host() == "127.0.0.1"
    with patch.dict("os.environ", {"MEMORY_DASHBOARD_PORT": "9100", "MEMORY_DASHBOARD_HOST": "localhost"}):
        assert default_dashboard_port() == 9100
        assert default_dashboard_host() == "localhost"
    with patch.dict("os.environ", {"MEMORY_DASHBOARD_PORT": "not-a-port"}):
        assert default_dashboard_port() == DEFAULT_DASHBOARD_PORT


def luminance(hex_color):
    parts = [int(hex_color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in parts]
    return sum(a * b for a, b in zip(linear, (.2126, .7152, .0722)))


def contrast(a, b):
    values = sorted([luminance(a), luminance(b)])
    return (values[1] + .05) / (values[0] + .05)


@pytest.mark.parametrize("theme", ["light", "dark", "colorblind-light", "colorblind-dark"])
def test_palette_text_and_control_contrast(theme):
    css = (Path(__file__).resolve().parents[1] / "memory_hub/static/app.css").read_text()
    match = re.search(r'\[data-theme="' + theme + r'"\]\s*\{([^}]+)', css)
    colors = dict(re.findall(r'--([\w-]+):\s*(#[0-9a-fA-F]{6})', match.group(1)))
    text_pairs = [(fg, bg) for fg in ("ink", "muted", "blue")
                  for bg in ("paper", "wash", "field", "collection", "hover", "selected")]
    text_pairs += [("chip-text", "chip-bg"), ("muted", "subtle-bg"),
                   ("danger", "paper"), ("danger", "error-bg"), ("on-primary", "primary"),
                   ("nav", "rail"), ("nav-muted", "rail"), ("on-rail", "nav-active")]
    for fg, bg in text_pairs:
        assert contrast(colors[fg], colors[bg]) >= 4.5, (theme, fg, bg, contrast(colors[fg], colors[bg]))
    for bg in ("paper", "field", "collection"):
        assert contrast(colors["line"], colors[bg]) >= 3, (theme, "line", bg)
    assert contrast(colors["focus"], colors["paper"]) >= 3


def test_theme_controls_and_safe_renderer_packaged():
    html = load_html()
    assert 'id="dark-mode" type="checkbox" role="switch"' in html
    assert 'id="colorblind-mode" type="checkbox" role="switch"' in html
    assert "localStorage.setItem('memory-hub-appearance'" in html
    assert "function inline(text){return esc(text)" in html
    assert "b.type='button'" in html
    assert "__CSS__" not in html and "__JS__" not in html
def test_javascript_interactions_without_browser():
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('Optional developer Node runtime is not installed; app does not require it.')
    subprocess.run([node, 'tests/dashboard_ui.cjs'],
                   cwd=Path(__file__).resolve().parents[1], check=True, timeout=15)


def test_tray_failure_keeps_browser_service_and_cleans_up():
    from unittest.mock import MagicMock
    fake_manager, fake_server, fake_thread = MagicMock(), MagicMock(), MagicMock()
    fake_server.server_address = ('127.0.0.1', 9999)
    fake_thread.join.side_effect = [KeyboardInterrupt(), None]
    fake_thread.is_alive.return_value = True
    with patch('memory_hub.app.running_instance', return_value=False), \
         patch('memory_hub.app.MemoryManager', return_value=fake_manager), \
         patch('memory_hub.app.create_server', return_value=fake_server), \
         patch('memory_hub.app.threading.Thread', return_value=fake_thread), \
         patch('memory_hub.app.webbrowser.open') as opened, \
         patch.dict('sys.modules', {'pystray': None}):
        run('demo', port=9999)
    opened.assert_called_once_with('http://127.0.0.1:9999/')
    fake_thread.start.assert_called_once()
    fake_server.shutdown.assert_called_once()
    fake_server.server_close.assert_called_once()
    fake_manager.close.assert_called_once()
