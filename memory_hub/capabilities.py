"""Per-client capability health for the dashboard and doctor command.

Aggregates observation-buffer statistics and hook-installation status for
each connected client into a single health report the dashboard renders
and the ``ai-memory doctor --clients`` command prints.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .capture import ObservationBuffer, _CLIENT_ALIASES
from .events import (
    SESSION_START,
    SESSION_END,
    USER_PROMPT_SUBMIT,
    PRE_TOOL_USE,
    POST_TOOL_USE,
    POST_TOOL_USE_FAILURE,
    PRE_COMPACT,
    POST_COMPACTION,
    STOP,
    STOP_FAILURE,
    INTERRUPT,
    SESSION_HEARTBEAT,
    SUBAGENT_STOP,
)
from .hooks import (
    MANAGED_KEY,
    _HERMES_BLOCK_RE,
    _toml_managed_ranges,
)
from .worker import read_health

# Every normalized event the pipeline understands.
ALL_EVENTS = [
    SESSION_START,
    USER_PROMPT_SUBMIT,
    PRE_TOOL_USE,
    POST_TOOL_USE,
    POST_TOOL_USE_FAILURE,
    STOP,
    STOP_FAILURE,
    INTERRUPT,
    PRE_COMPACT,
    POST_COMPACTION,
    SESSION_HEARTBEAT,
    SUBAGENT_STOP,
    SESSION_END,
]

EVENT_LABELS: dict[str, str] = {
    SESSION_START: "Session start",
    USER_PROMPT_SUBMIT: "User prompt",
    PRE_TOOL_USE: "Pre-tool use",
    POST_TOOL_USE: "Post-tool use",
    POST_TOOL_USE_FAILURE: "Tool failure",
    STOP: "Turn stop",
    STOP_FAILURE: "Stop failure",
    INTERRUPT: "Interrupt",
    PRE_COMPACT: "Pre-compact",
    POST_COMPACTION: "Post-compaction",
    SESSION_HEARTBEAT: "Heartbeat",
    SUBAGENT_STOP: "Sub-agent stop",
    SESSION_END: "Session end",
}

# (client_key, default_settings_path_or_None, format_hint, display_name)
# format_hint matches --format values in cli.py.
CLIENT_PROFILES: list[tuple[str, str | None, str, str]] = [
    ("claude", "~/.claude/settings.json", "claude", "Claude Code"),
    ("codex", "~/.codex/hooks.json", "codex", "Codex CLI"),
    ("gemini", "~/.gemini/settings.json", "nested", "Gemini CLI"),
    ("qwen", "~/.qwen/settings.json", "nested", "Qwen Code"),
    ("kimi", "~/.kimi-code/config.toml", "kimi-toml", "Kimi Code"),
    ("hermes", None, "hermes-yaml", "Hermes Agent"),
]


def _compute_buffer_stats(buf: ObservationBuffer) -> dict[str, Any]:
    """Return per-source statistics from the observation buffer.

    Computes event counts, last-capture timestamp, and pending-buffer
    depth for each source (client) that has submitted observations.
    """
    conn = buf.conn
    rows = conn.execute(
        """SELECT source,
                  COUNT(*) AS total,
                  COUNT(DISTINCT event) AS event_type_count,
                  MAX(created_at) AS last_capture,
                  SUM(CASE WHEN status IN ('pending','failed') THEN 1 ELSE 0 END) AS pending
           FROM observations
           GROUP BY source
           ORDER BY source"""
    ).fetchall()
    sources: dict[str, Any] = {}
    for row in rows:
        source = str(row[0]) if row[0] else "unknown"
        sources[source] = {
            "total_observations": int(row[1]),
            "supported_event_count": int(row[2]),
            "last_capture": str(row[3]) if row[3] else None,
            "pending_buffer_depth": int(row[4]),
        }
    event_rows = conn.execute(
        """SELECT source, event, COUNT(*) AS count
           FROM observations
           GROUP BY source, event"""
    ).fetchall()
    for row in event_rows:
        source = str(row[0]) if row[0] else "unknown"
        event = str(row[1])
        sources.setdefault(source, {})
        if "events" not in sources[source]:
            sources[source]["events"] = {}
        sources[source]["events"][event] = int(row[2])
    return sources


def _looks_managed(handler: dict[str, Any]) -> bool:
    """Detect non-``ai_memory_hub_managed`` markers (Codex/Hermes)."""
    status = str(handler.get("statusMessage", ""))
    name = str(handler.get("name", ""))
    return status.startswith("AI Memory Hub") or name.startswith("ai-memory-hub")


def _check_json_settings(path: Path) -> dict[str, Any]:
    """Look for managed ai-memory-hub hooks in a JSON settings file."""
    if not path.exists():
        return {"installed": False, "events": [], "error": None}
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"installed": False, "events": [], "error": str(exc)}
    if not isinstance(config, dict):
        return {"installed": False, "events": [], "error": "not a JSON object"}
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        return {"installed": False, "events": [], "error": None}
    found_events: list[str] = []
    for event_name, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("hooks"), list):
                for handler in entry["hooks"]:
                    if isinstance(handler, dict):
                        if handler.get(MANAGED_KEY) or _looks_managed(handler):
                            if event_name not in found_events:
                                found_events.append(event_name)
            elif isinstance(entry, dict) and entry.get(MANAGED_KEY):
                if event_name not in found_events:
                    found_events.append(event_name)
    return {"installed": bool(found_events), "events": sorted(found_events), "error": None}


def _check_toml_settings(path: Path) -> dict[str, Any]:
    """Look for managed TOML hook blocks (Kimi)."""
    if not path.exists():
        return {"installed": False, "events": [], "error": None}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"installed": False, "events": [], "error": str(exc)}
    try:
        ranges = _toml_managed_ranges(content)
    except Exception as exc:
        return {"installed": False, "events": [], "error": str(exc)}
    found_events: list[str] = []
    for start, end in ranges:
        block = content[start:end]
        for line in block.splitlines():
            if line.strip().startswith("event = "):
                event = line.split("=", 1)[1].strip().strip('"')
                if event not in found_events:
                    found_events.append(event)
    return {"installed": bool(found_events), "events": sorted(found_events), "error": None}


def _check_hermes_settings(path: Path) -> dict[str, Any]:
    """Look for managed Hermes YAML hook entries."""
    if not path.exists():
        return {"installed": False, "events": [], "error": None}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"installed": False, "events": [], "error": str(exc)}
    found_events = [m.group("event") for m in _HERMES_BLOCK_RE.finditer(content)]
    return {"installed": bool(found_events), "events": sorted(set(found_events)), "error": None}


def check_hook_status(settings_path: Path | str | None, format_hint: str) -> dict[str, Any]:
    """Dispatch to the correct checker based on the client format."""
    if not settings_path:
        return {"installed": False, "events": [], "error": "no settings path"}
    path = Path(settings_path).expanduser()
    if format_hint == "hermes-yaml":
        return _check_hermes_settings(path)
    if format_hint == "kimi-toml":
        return _check_toml_settings(path)
    return _check_json_settings(path)


def _find_hermes_config() -> Path | None:
    """Locate the active Hermes profile config.yaml."""
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if not local_appdata:
        return None
    profiles_dir = Path(local_appdata) / "hermes" / "profiles"
    if not profiles_dir.is_dir():
        return None
    for profile in ("aimemoryhub", "default"):
        candidate = profiles_dir / profile / "config.yaml"
        if candidate.exists():
            return candidate
    for child in sorted(profiles_dir.iterdir()):
        candidate = child / "config.yaml"
        if candidate.is_file():
            return candidate
    return None


def _client_stats(client_key: str, stats: dict[str, Any]) -> dict[str, Any]:
    """Find stats rows matching this client (by source or alias)."""
    if client_key in stats:
        return stats[client_key]
    for alias, canonical in _CLIENT_ALIASES.items():
        if canonical == client_key and alias in stats:
            return stats[alias]
    return {
        "total_observations": 0,
        "supported_event_count": 0,
        "last_capture": None,
        "pending_buffer_depth": 0,
        "events": {},
    }


def gather_capabilities(
    vault: Path | str | None = None,
    buffer: ObservationBuffer | None = None,
    *,
    include_hermes: bool = True,
) -> dict[str, Any]:
    """Build the full capabilities report for the dashboard / doctor."""
    buf_owned = buffer is None
    buf = buffer or ObservationBuffer()
    try:
        stats = _compute_buffer_stats(buf)
    finally:
        if buf_owned:
            buf.close()

    clients: list[dict[str, Any]] = []
    for client_key, settings_rel, format_hint, display_name in CLIENT_PROFILES:
        if client_key == "hermes" and not include_hermes:
            continue
        if client_key == "hermes":
            settings_path = _find_hermes_config()
            settings_str = str(settings_path) if settings_path else None
        else:
            settings_str = settings_rel
            settings_path = Path(settings_rel).expanduser() if settings_rel else None
        hook = check_hook_status(settings_path, format_hint) if settings_path else {
            "installed": False, "events": [], "error": "no settings path",
        }
        source_data = _client_stats(client_key, stats)
        clients.append({
            "key": client_key,
            "display_name": display_name,
            "settings_path": settings_str,
            "hook_format": format_hint,
            "hook_installed": hook["installed"],
            "hook_events": hook["events"],
            "hook_error": hook.get("error"),
            "buffer": source_data,
        })

    worker = read_health(Path(vault).expanduser() if vault else Path("."))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "all_events": ALL_EVENTS,
        "event_labels": EVENT_LABELS,
        "clients": clients,
        "worker": worker,
    }


def check_mcp_connectivity() -> dict[str, Any]:
    """Verify the MCP server can be imported and its tools load."""
    try:
        from . import mcp_server
    except ImportError as exc:
        return {"status": "error", "error": f"cannot import mcp_server: {exc}"}
    tools: list[str] = []
    try:
        mcp_instance = mcp_server.mcp
        handlers = getattr(mcp_instance, "_tool_handlers", {}) or {}
        tools = sorted(handlers.keys())
    except Exception:
        pass
    return {
        "status": "ok" if tools else "degraded",
        "tool_count": len(tools),
        "tools": tools,
    }


def check_encryption_status() -> dict[str, Any]:
    """Report encryption/secrets-detection configuration status."""
    from .security import SECRET_PATTERNS
    return {
        "encryption_at_rest": False,
        "secret_detection_active": bool(SECRET_PATTERNS),
        "secret_pattern_count": len(SECRET_PATTERNS),
        "note": "Secrets are redacted in the capture pipeline; the vault is not encrypted at rest.",
    }
