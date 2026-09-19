"""Tests for capability health dashboard and doctor command."""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from memory_hub.capabilities import (
    ALL_EVENTS,
    CLIENT_PROFILES,
    _check_hermes_settings,
    _check_json_settings,
    _check_toml_settings,
    _compute_buffer_stats,
    _looks_managed,
    check_encryption_status,
    check_mcp_connectivity,
    gather_capabilities,
)
from memory_hub.capture import ObservationBuffer
from memory_hub.dashboard import DashboardHandler
from memory_hub.manager import MemoryManager


class BufferStatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.buf = ObservationBuffer(Path(self.tmp.name) / "obs.sqlite3")

    def tearDown(self):
        self.buf.close()
        self.tmp.cleanup()

    def test_empty_buffer_returns_empty_dict(self):
        stats = _compute_buffer_stats(self.buf)
        assert stats == {}

    def test_single_source_stats(self):
        self.buf.append({
            "session_id": "sess-1",
            "client": "claude",
            "event": "session-start",
            "input_summary": "start",
        })
        self.buf.append({
            "session_id": "sess-1",
            "client": "claude",
            "event": "user-prompt-submit",
            "input_summary": "hello",
        })
        self.buf.append({
            "session_id": "sess-1",
            "client": "claude",
            "event": "session-end",
            "input_summary": "end",
        })
        stats = _compute_buffer_stats(self.buf)
        assert "claude" in stats
        assert stats["claude"]["total_observations"] == 3
        assert stats["claude"]["supported_event_count"] == 3
        assert stats["claude"]["pending_buffer_depth"] == 3
        assert "events" in stats["claude"]
        assert stats["claude"]["events"]["session-start"] == 1

    def test_multiple_sources(self):
        self.buf.append({
            "session_id": "s1", "client": "claude", "event": "session-start",
            "input_summary": "s",
        })
        self.buf.append({
            "session_id": "s2", "client": "codex", "event": "session-start",
            "input_summary": "s",
        })
        stats = _compute_buffer_stats(self.buf)
        assert len(stats) == 2
        assert "claude" in stats
        assert "codex" in stats


class ManagedDetectionTests(unittest.TestCase):
    def test_managed_key_marker(self):
        assert _looks_managed({"statusMessage": "AI Memory Hub capture"})
        assert _looks_managed({"name": "ai-memory-hub-context"})

    def test_not_managed(self):
        assert not _looks_managed({"statusMessage": "other"})
        assert not _looks_managed({"command": "ai-memory-hook"})
        assert not _looks_managed({})


class CheckJsonSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file(self):
        result = _check_json_settings(self.path)
        assert not result["installed"]
        assert result["events"] == []

    def test_installed_claude_format(self):
        self.path.write_text(json.dumps({
            "hooks": {
                "PostToolUse": [
                    {"matcher": "*", "hooks": [
                        {"type": "command", "command": "ai-memory-hook",
                         "ai_memory_hub_managed": True}
                    ]}
                ]
            }
        }, indent=2), encoding="utf-8")
        result = _check_json_settings(self.path)
        assert result["installed"]
        assert "PostToolUse" in result["events"]

    def test_installed_codex_format(self):
        self.path.write_text(json.dumps({
            "hooks": {
                "post-tool-use": [
                    {"matcher": "*", "hooks": [
                        {"type": "command", "command": "ai-memory-hook",
                         "statusMessage": "AI Memory Hub capture"}
                    ]}
                ]
            }
        }, indent=2), encoding="utf-8")
        result = _check_json_settings(self.path)
        assert result["installed"]

    def test_no_managed_hooks(self):
        self.path.write_text(json.dumps({
            "hooks": {
                "PostToolUse": [
                    {"matcher": "*", "hooks": [
                        {"type": "command", "command": "other-hook"}
                    ]}
                ]
            }
        }, indent=2), encoding="utf-8")
        result = _check_json_settings(self.path)
        assert not result["installed"]


class CheckTomlSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.toml"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file(self):
        result = _check_toml_settings(self.path)
        assert not result["installed"]

    def test_installed_toml(self):
        self.path.write_text(
            '# ai-memory-hub managed hook\n'
            '[[hooks]]\n'
            'event = "post-tool-use"\n'
            'command = "ai-memory-hook"\n',
            encoding="utf-8",
        )
        result = _check_toml_settings(self.path)
        assert result["installed"]
        assert "post-tool-use" in result["events"]


class CheckHermesSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file(self):
        result = _check_hermes_settings(self.path)
        assert not result["installed"]

    def test_installed_hermes(self):
        self.path.write_text(
            'hooks:\n'
            '  post-tool-call:\n'
            '  # ai-memory-hub managed hook event=post_tool_call\n'
            '  - command: "ai-memory-hook"\n'
            '    timeout: 20\n',
            encoding="utf-8",
        )
        result = _check_hermes_settings(self.path)
        assert result["installed"]
        assert "post_tool_call" in result["events"]


class GatherCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.manager = MemoryManager(self.vault)
        template = Path(__file__).resolve().parent.parent / "vault_template"
        self.manager.initialize(template)
        self.buf = ObservationBuffer(Path(self.tmp.name) / "obs.sqlite3")

    def tearDown(self):
        self.buf.close()
        self.manager.close()
        self.tmp.cleanup()

    def test_basic_structure(self):
        cap = gather_capabilities(str(self.vault), self.buf)
        assert "generated_at" in cap
        assert "all_events" in cap
        assert "event_labels" in cap
        assert "clients" in cap
        assert "worker" in cap
        assert len(cap["clients"]) == len(CLIENT_PROFILES)

    def test_event_labels_complete(self):
        cap = gather_capabilities(str(self.vault), self.buf)
        for ev in ALL_EVENTS:
            assert ev in cap["event_labels"]

    def test_client_keys_match_profiles(self):
        cap = gather_capabilities(str(self.vault), self.buf)
        profile_keys = [p[0] for p in CLIENT_PROFILES]
        client_keys = [c["key"] for c in cap["clients"]]
        assert client_keys == profile_keys

    def test_includes_buffer_stats(self):
        self.buf.append({
            "session_id": "s1", "client": "claude", "event": "session-start",
            "input_summary": "start",
        })
        cap = gather_capabilities(str(self.vault), self.buf)
        claude = next(c for c in cap["clients"] if c["key"] == "claude")
        assert claude["buffer"]["total_observations"] == 1

    def test_no_observations_returns_zeroed_buffer(self):
        cap = gather_capabilities(str(self.vault), self.buf)
        for client in cap["clients"]:
            assert client["buffer"]["total_observations"] == 0
            assert client["buffer"]["pending_buffer_depth"] == 0


class McpConnectivityTests(unittest.TestCase):
    def test_imports_and_returns_dict(self):
        result = check_mcp_connectivity()
        assert "status" in result
        assert "tool_count" in result
        assert "tools" in result
        assert isinstance(result["tools"], list)


class EncryptionStatusTests(unittest.TestCase):
    def test_returns_expected_keys(self):
        result = check_encryption_status()
        assert "encryption_at_rest" in result
        assert "secret_detection_active" in result
        assert "secret_pattern_count" in result
        assert isinstance(result["encryption_at_rest"], bool)


class DashboardCapabilitiesEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.manager = MemoryManager(self.vault)
        template = Path(__file__).resolve().parent.parent / "vault_template"
        self.manager.initialize(template)

        DashboardHandler.manager = self.manager
        DashboardHandler.launch_token = "test-token"
        from http.server import ThreadingHTTPServer
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        DashboardHandler.allowed_hosts = frozenset(
            {f"127.0.0.1:{self.httpd.server_address[1]}"}
        )
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.thread.join(timeout=5)
        self.httpd.server_close()
        self.manager.close()
        self.tmp.cleanup()

    def test_capabilities_endpoint_returns_json(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/api/capabilities", headers={
            "Host": f"127.0.0.1:{self.port}",
            "X-Launch-Token": "test-token",
        })
        resp = conn.getresponse()
        assert resp.status == 200
        body = json.loads(resp.read())
        conn.close()
        assert "clients" in body
        assert "generated_at" in body

    def test_capabilities_endpoint_forbids_without_token(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/api/capabilities", headers={
            "Host": f"127.0.0.1:{self.port}",
        })
        resp = conn.getresponse()
        assert resp.status == 403
        resp.read()
        conn.close()

    def test_capabilities_response_has_expected_clients(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/api/capabilities", headers={
            "Host": f"127.0.0.1:{self.port}",
            "X-Launch-Token": "test-token",
        })
        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()
        client_keys = {c["key"] for c in body["clients"]}
        expected = {p[0] for p in CLIENT_PROFILES}
        assert client_keys == expected


class DoctorCliTests(unittest.TestCase):
    def test_doctor_help_includes_clients(self):
        from memory_hub.cli import build_parser
        parser = build_parser()
        # Just make sure --clients parses without error.
        args = parser.parse_args(["doctor", "--clients"])
        assert args.clients
        assert not args.json

    def test_doctor_json_flag(self):
        from memory_hub.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["doctor", "--clients", "--json"])
        assert args.json


if __name__ == "__main__":
    unittest.main()
