from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ._env import int_env
from .app_config import GROUPS, bootstrap_environment, effective_config, save_settings
from .auto_fix import fix_issue, scan_audit_issues
from .dashboard_data import detail, metadata, save_metadata
from .entities import resolve_subject
from .manager import MemoryManager
from .utils import slugify
from .vault import FILE_PER_ENTITY_KINDS

logger = logging.getLogger(__name__)

ASSETS = Path(__file__).with_name('static')

# The single source of truth for the dashboard's bind address/port: app.py,
# dashboard.py and the *.ps1 launchers all previously hardcoded 8765 independently,
# so changing it meant editing five files consistently and a missed one made
# app.py's single-instance probe silently check the wrong port (#81).
DEFAULT_DASHBOARD_HOST = '127.0.0.1'
DEFAULT_DASHBOARD_PORT = 8765


def default_dashboard_host() -> str:
    return os.environ.get('MEMORY_DASHBOARD_HOST', '').strip() or DEFAULT_DASHBOARD_HOST


def default_dashboard_port() -> int:
    return int_env('MEMORY_DASHBOARD_PORT', DEFAULT_DASHBOARD_PORT)


def load_html():
    return (ASSETS.joinpath('index.html').read_text(encoding='utf-8')
        .replace('__CSS__', ASSETS.joinpath('app.css').read_text(encoding='utf-8'))
        .replace('__JS__', ASSETS.joinpath('app.js').read_text(encoding='utf-8')))


HTML = load_html()
def _dashboard_group(row: dict, registry: dict[str, dict[str, str]]) -> tuple[str, str]:
    """(group_key, group_label) for one index row.

    FILE_PER_ENTITY_KINDS (project, and since #35 also topic/decision/person)
    route one file per entity, so routing may place several related subjects
    in one file -- group by that file, not by subject, the way project always
    did. Shared-file kinds (preference, profile) route every subject into one
    file regardless of entity, so grouping must resolve through the
    entity-aliases.md registry instead, or a linked pair (#35) would still
    render as two unrelated cards.
    """
    kind = row["kind"]
    if kind in FILE_PER_ENTITY_KINDS:
        label = row["path"].rsplit("/", 1)[-1]
        if label.endswith(".md"):
            label = label[:-3]
        return f"{kind}:{row['path']}", label
    subject = row["subject"] or "general"
    if kind in registry:
        subject = resolve_subject(registry, kind, slugify(subject))
    return f"{kind}:{subject}", subject

def _pending_rows_for_dashboard(rows: list[dict]) -> list[dict]:
    """Parse each row's stored `payload` (a JSON *string* column, per
    MemoryIndex.enqueue) into a nested object so the review-queue card can
    render a session's four sections or a pattern's two halves structurally,
    instead of only the single flattened `text` field every kind already has.

    Backward compatible by construction: a row with no payload, or a payload
    that fails to parse, is returned with `payload: None` untouched -- exactly
    what every pre-existing proposal (and every non-session/non-pattern kind)
    already looks like. This never touches the database; MemoryManager.approve()
    reads its own row via a separate fetch and is unaffected (#38).
    """
    for row in rows:
        raw = row.get("payload")
        try:
            row["payload"] = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            row["payload"] = None
    return rows

def memory_rows_for_dashboard(manager: MemoryManager, query: str = "") -> list[dict]:
    """Return visible dashboard rows with recency calculated from the full index."""
    registry = manager.entity_registry()
    all_rows = manager.index.all_rows()
    newest = {}
    for row in all_rows:
        key, _ = _dashboard_group(row, registry)
        if key not in newest or (row["date"], row["memory_id"]) > (newest[key]["date"], newest[key]["memory_id"]):
            newest[key] = row
    rows = list(reversed(all_rows))  # newest first; sorted via index ORDER BY DESC (#166)
    organization = metadata(manager)
    if query:
        rows = [row for row in rows if query.casefold() in
                ' '.join(str(row.get(key, '')) for key in
                         ('text', 'subject', 'writer', 'path')).casefold()]
    for row in rows:
        row['tags'] = organization.get(row['memory_id'], {}).get('tags', [])
        key, label = _dashboard_group(row, registry)
        row["is_most_recent"] = newest.get(key, {}).get("memory_id") == row["memory_id"]
        row["group_key"] = key
        row["group_label"] = label
    return rows

class DashboardHandler(BaseHTTPRequestHandler):
    manager: MemoryManager = None  # type: ignore
    # Random per-launch token the page must echo back on every state-changing
    # request, plus the exact Host values this server considers itself bound to.
    # Localhost binding alone does not stop DNS rebinding (which affects GET too —
    # see _host_ok) or cross-origin POSTs from a page the browser merely happens
    # to have open (#6).
    launch_token: str = ""
    allowed_hosts: frozenset = frozenset()

    def log_message(self, format, *args):
        return

    def _host_ok(self) -> bool:
        # DNS rebinding sends the *hostname* the page's JS used (e.g. attacker.com),
        # even once that name resolves to 127.0.0.1 — checking Host, not the socket's
        # peer address, is what actually distinguishes a rebound request from a
        # legitimate one, for GET as much as for POST: an unauthenticated GET is
        # exactly what rebinding is for, since it lets the attacker's now-same-origin
        # JS read the response (list memories, pending proposals, audit) that a
        # cross-origin fetch could not read without CORS headers this server never sends.
        return self.headers.get("Host", "") in self.allowed_hosts

    def _origin_ok(self) -> bool:
        if not self._host_ok():
            return False
        origin = self.headers.get("Origin")
        if origin and (urlparse(origin).scheme != 'http' or urlparse(origin).netloc not in self.allowed_hosts):
            return False
        token = self.headers.get("X-Launch-Token", "")
        return secrets.compare_digest(token, self.launch_token)

    def _json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        # Hardened response headers: block MIME sniffing, lock down referrer
        # leakage, and restrict resource loading to same-origin (#170).
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; "
                         "script-src 'unsafe-inline'; img-src data:; "
                         "connect-src 'self'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or "0")
        if n < 0 or n > 65536:
            raise ValueError('Maximum request size is 64 KiB.')
        if not n:
            return {}
        body = json.loads(self.rfile.read(n).decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("Request must be a JSON object.")
        return body

    def do_GET(self):
        self._get()

    def _get(self):
        if not self._host_ok():
            return self._json({"error": "forbidden: bad host"}, 403)
        u = urlparse(self.path)
        if u.path == "/":
            data = HTML.replace("__LAUNCH_TOKEN__", self.launch_token).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if u.path == '/api/instance':
            from .dashboard_data import revision
            return self._json({'app': 'ai-memory-hub', 'vault': revision(str(self.manager.vault.root.resolve()))})
        if not self._origin_ok():
            return self._json({"error": "forbidden: bad host/origin/launch token"}, 403)
        try:
            if u.path == "/api/memories":
                q = parse_qs(u.query).get("q", [""])[0]
                page = int(parse_qs(u.query).get("page", ["1"])[0])
                page_size = min(200, max(1, int(parse_qs(u.query).get("page_size", ["50"])[0])))
                rows = memory_rows_for_dashboard(self.manager, q)
                total = len(rows)
                start = (page - 1) * page_size
                end = start + page_size
                return self._json({
                    "rows": rows[start:end],
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "total_pages": max(1, (total + page_size - 1) // page_size),
                })
            if u.path.startswith('/api/memory/'):
                return self._json(detail(self.manager, u.path.rsplit('/', 1)[-1]))
            if u.path == "/api/pending":
                if parse_qs(u.query).get("history", ["0"])[0] == "1":
                    return self._json(_pending_rows_for_dashboard(self.manager.list_proposal_history()))
                return self._json(_pending_rows_for_dashboard(self.manager.list_pending()))
            if u.path == "/api/conflicts":
                return self._json(self.manager.conflicts())
            if u.path == "/api/audit":
                return self._json(self.manager.audit())
            if u.path == "/api/audit/issues":
                return self._json({"issues": scan_audit_issues(self.manager)})
            if u.path == "/api/capabilities":
                from .capabilities import gather_capabilities
                return self._json(gather_capabilities(self.manager.vault.root))
            if u.path == "/api/worker-health":
                from .worker import read_health
                return self._json(read_health(self.manager.vault.root))
            if u.path == "/api/config":
                return self._json({"groups": GROUPS, "settings": effective_config(self.manager.vault.root)})
            return self._json({"error": "not found"}, 404)
        except KeyError as exc:
            self._json({"error": str(exc)}, 404)
        except (ValueError, TypeError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception:
            correlation_id = secrets.token_hex(8)
            logger.exception("Unhandled error in dashboard handler (correlation_id=%s)", correlation_id)
            self._json({"error": "An internal error occurred. See logs for details.",
                        "correlation_id": correlation_id}, 500)

    def do_POST(self):
        self._post()

    def _post(self):
        u = urlparse(self.path)
        if not self._origin_ok():
            return self._json({"error": "forbidden: bad host/origin/launch token"}, 403)
        try:
            body = self._body()
            parts = [p for p in u.path.split("/") if p]
            if len(parts) == 4 and parts[:2] == ['api', 'memory'] and parts[3] == 'metadata':
                result = save_metadata(self.manager, parts[2], body)
                return self._json(result, 409 if result.get('status') == 'conflict' else 200)
            if len(parts) == 4 and parts[:2] == ["api", "pending"] and parts[3] == "approve":
                return self._json(self.manager.approve(parts[2]))
            if len(parts) == 4 and parts[:2] == ["api", "pending"] and parts[3] == "reject":
                return self._json(self.manager.reject(parts[2], str(body.get("note", ""))))
            if len(parts) == 4 and parts[:2] == ["api", "memory"] and parts[3] == "forget":
                return self._json(self.manager.forget(parts[2]))
            if len(parts) == 4 and parts[:2] == ["api", "memory"] and parts[3] == "edit":
                return self._json(self.manager.edit(parts[2], str(body.get("text", "")), writer="user"))
            if u.path == "/api/conflict/resolve":
                return self._json(self.manager.resolve_conflict(str(body["keep_id"])))
            if u.path == "/api/config":
                settings = save_settings(self.manager.vault.root, body)
                return self._json({"status": "saved", "settings": settings})
            if u.path == "/api/fix-issue":
                result = fix_issue(
                    self.manager,
                    issue_type=str(body.get("issue_type", "")),
                    summary=str(body.get("summary", "")),
                    severity=str(body.get("severity", "warning")),
                    fixable=bool(body.get("fixable", False)),
                    path=body.get("path"),
                    line=body.get("line"),
                    text=body.get("text"),
                    heading=body.get("heading"),
                    memory_id=body.get("memory_id"),
                )
                return self._json(result)
            self._json({"error": "not found"}, 404)
        except KeyError as exc:
            self._json({"error": str(exc)}, 404)
        except (ValueError, TypeError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception:
            correlation_id = secrets.token_hex(8)
            logger.exception("Unhandled error in dashboard handler (correlation_id=%s)", correlation_id)
            self._json({"error": "An internal error occurred. See logs for details.",
                        "correlation_id": correlation_id}, 500)

class _LocalDashboardHandlerBase(DashboardHandler):
    """Base class for per-launch dashboard handlers.

    Each call to ``create_server`` creates a fresh *subclass* of this base
    with its own ``manager`` and ``launch_token`` class attributes. This
    avoids the ``type()`` anti-pattern (#220) while keeping launches isolated.
    """
    manager: MemoryManager | None = None
    launch_token: str | None = None

    def __init__(self, request, client_address, server):
        super().__init__(request, client_address, server)


def create_server(manager: MemoryManager, host: str | None = None, port: int | None = None):
    """Every launch path receives an isolated token, host guard."""
    host = host if host is not None else default_dashboard_host()
    port = port if port is not None else default_dashboard_port()
    if host not in ('127.0.0.1', 'localhost'):
        raise ValueError('The memory dashboard only supports loopback access.')
    # Create a fresh subclass per launch so each server has its own token/manager
    handler = type(f'LocalDashboard{abs(hash(manager)) % 10000:04d}', (_LocalDashboardHandlerBase,), {
        'manager': manager, 'launch_token': secrets.token_urlsafe(24),
    })
    server = ThreadingHTTPServer((host, port), handler)
    actual_port = server.server_address[1]
    handler.allowed_hosts = frozenset(f'{name}:{actual_port}' for name in ('127.0.0.1', 'localhost'))
    return server


def serve(vault: str, host: str | None = None, port: int | None = None, open_browser: bool = True):
    bootstrap_environment(vault)  # config.json fills gaps; an explicit env var still wins.
    host = host if host is not None else default_dashboard_host()
    port = port if port is not None else default_dashboard_port()
    manager = MemoryManager(vault)
    httpd = None
    try:
        httpd = create_server(manager, host, port)
        manager.reindex()
        url = f"http://{host}:{httpd.server_address[1]}/"
        if open_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        print(f"AI Memory Hub dashboard: {url}", flush=True)
        print("Bound to localhost only. Press Ctrl+C to stop.", flush=True)
        httpd.serve_forever()
    finally:
        if httpd:
            httpd.server_close()
        manager.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vault", default=os.environ.get("AI_MEMORY_VAULT"))
    # No default on host/port here: they may come from the vault's config.json,
    # which isn't known until serve() bootstraps it from --vault.
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    if not args.vault:
        p.error("Set --vault or AI_MEMORY_VAULT")
    serve(args.vault, args.host, args.port, not args.no_browser)

if __name__ == "__main__":
    main()
