"""Per-vault application configuration, and the environment bootstrap that
makes it take effect without a dotenv loader.

No process in this project reads a `.env` file automatically -- every setting
is read directly from `os.environ` at the point of use. That leaves two ways
to change a setting: export a real environment variable yourself, or store it
here in `<vault>/.ai-memory-hub/config.json` and let `bootstrap_environment`
seed `os.environ` from it the moment a process starts.

`bootstrap_environment` uses `setdefault` semantics only: an environment
variable a caller already set (a client's own MCP registration, CI, a manual
`$env:` override) always wins over the file. The file is the default source
for "settings changed through the dashboard's Settings pane"; an explicit env
var stays the escape hatch for a one-off override without touching the file.

SETTINGS_SCHEMA is also the single source of truth the dashboard's Settings
API renders from (`GET /api/config`) and validates against (`POST
/api/config`) -- add a setting here once and both the backend and the
frontend form pick it up.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .utils import atomic_write

CONFIG_FILENAME = "config.json"

GROUPS: list[dict[str, str]] = [
    {"key": "identity", "label": "Vault & Identity"},
    {"key": "write_mode", "label": "Write Mode"},
    {"key": "capture", "label": "Capture"},
    {"key": "transcript", "label": "Transcript"},
    {"key": "worker", "label": "Worker"},
    {"key": "dashboard", "label": "Dashboard"},
    {"key": "models", "label": "LLM & Embeddings"},
    {"key": "github", "label": "GitHub Export"},
]

SETTINGS_SCHEMA: list[dict[str, Any]] = [
    {"key": "MEMORY_WRITER", "group": "identity", "label": "Default writer identity", "type": "select",
     "options": ["chatgpt", "claude", "codex", "gemini", "kimi", "qwen", "cursor", "hermes", "user", "other"],
     "default": "claude",
     "description": "Used when a process is launched directly (worker, dashboard, a manual MCP server) rather than through a connected client -- each connected client sets its own identity automatically."},
    {"key": "MEMORY_WRITE_MODE", "group": "write_mode", "label": "Write mode", "type": "select",
     "options": ["review", "auto"], "default": "review",
     "description": "review queues every AI-proposed memory for your approval. auto writes valid proposals straight to the vault."},
    {"key": "MEMORY_VAULT_HISTORY", "group": "write_mode", "label": "Commit a vault git history entry on every successful write", "type": "bool",
     "default": False, "description": "Undo support: keeps a git history entry per accepted write."},
    {"key": "MEMORY_CAPTURE_DB", "group": "capture", "label": "Capture database path", "type": "text", "default": "",
     "description": "Leave blank to use the per-vault default."},
    {"key": "MEMORY_CAPTURE_RETENTION_DAYS", "group": "capture", "label": "Retention (days)", "type": "int",
     "default": 30, "min": 0, "max": 3650},
    {"key": "MEMORY_CAPTURE_EXCLUDE_PATHS", "group": "capture", "label": "Extra excluded path globs (comma-separated)",
     "type": "text", "default": "",
     "description": ".env, SSH/AWS credentials, .pem/.key files and similar are always excluded in addition to this."},
    {"key": "MEMORY_TRANSCRIPT_ENABLED", "group": "transcript", "label": "Persist raw provider events to a local transcript companion object",
     "type": "bool", "default": False,
     "description": "Prompts, responses, tool inputs/outputs and structured chat objects can be sensitive. Restart the hook receiver and worker after changing this."},
    {"key": "MEMORY_TRANSCRIPT_DB", "group": "transcript", "label": "Transcript database path", "type": "text", "default": ""},
    {"key": "MEMORY_TRANSCRIPT_RETENTION_DAYS", "group": "transcript", "label": "Retention (days, 0 = keep until forgotten)",
     "type": "int", "default": 0, "min": 0, "max": 3650},
    {"key": "MEMORY_WORKER_TOKEN_BUDGET", "group": "worker", "label": "Token budget before checkpoint", "type": "int",
     "default": 4000, "min": 100, "max": 1000000},
    {"key": "MEMORY_WORKER_FLUSH_SECONDS", "group": "worker", "label": "Flush age (s) — routine checkpoint", "type": "int",
     "default": 60, "min": 1, "max": 86400},
    {"key": "MEMORY_WORKER_IDLE_SECONDS", "group": "worker", "label": "Idle age (s) — provisional close", "type": "int",
     "default": 300, "min": 1, "max": 86400,
     "description": "Should be set well above Flush -- it only matters for a gap in activity longer than the routine checkpoint cadence."},
    {"key": "MEMORY_WORKER_INTERVAL_SECONDS", "group": "worker", "label": "Worker polling interval (s)", "type": "int",
     "default": 15, "min": 1, "max": 3600},
    {"key": "MEMORY_WORKER_BATCH_LIMIT", "group": "worker", "label": "Max observations claimed per pass", "type": "int",
     "default": 500, "min": 1, "max": 100000},
    {"key": "MEMORY_WORKER_HEALTH", "group": "worker", "label": "Worker health JSON path", "type": "text", "default": ""},
    {"key": "MEMORY_HANDOFF_MAX_CHARS", "group": "worker", "label": "Max startup handoff packet size (chars)", "type": "int",
     "default": 6000, "min": 500, "max": 12000},
    {"key": "MEMORY_DASHBOARD_HOST", "group": "dashboard", "label": "Bind address", "type": "select",
     "options": ["127.0.0.1", "localhost"], "default": "127.0.0.1",
     "description": "Loopback only -- the dashboard never binds to a public interface."},
    {"key": "MEMORY_DASHBOARD_PORT", "group": "dashboard", "label": "Port", "type": "int", "default": 8765, "min": 1, "max": 65535},
    {"key": "MEMORY_LLM_BASE_URL", "group": "models", "label": "Consolidation model base URL", "type": "text", "default": "",
     "description": "An OpenAI-compatible chat-completions endpoint (e.g. a local Ollama/LM Studio server). Leave blank to use the built-in conservative fallback summarizer."},
    {"key": "MEMORY_LLM_MODEL", "group": "models", "label": "Consolidation model name", "type": "text", "default": ""},
    {"key": "MEMORY_LLM_API_KEY", "group": "models", "label": "Consolidation model API key", "type": "password", "default": ""},
    {"key": "MEMORY_EMBED_BASE_URL", "group": "models", "label": "Embedding base URL", "type": "text", "default": "",
     "description": "Used only for semantic search and the duplicate/related-memory audit. Leave blank to disable embeddings; full-text search still works."},
    {"key": "MEMORY_EMBED_MODEL", "group": "models", "label": "Embedding model name", "type": "text", "default": "nomic-embed-text"},
    {"key": "MEMORY_GITHUB_EXPORT_INTERVAL_SECONDS", "group": "github", "label": "Exporter polling interval (s)", "type": "int",
     "default": 30, "min": 5, "max": 86400},
    {"key": "MEMORY_GITHUB_EXPORT_CONFIG", "group": "github", "label": "Export config path", "type": "text", "default": ""},
    {"key": "MEMORY_GITHUB_OUTBOX", "group": "github", "label": "Outbox database path", "type": "text", "default": ""},
    {"key": "MEMORY_GITHUB_HEALTH", "group": "github", "label": "Exporter health JSON path", "type": "text", "default": ""},
]

_BY_KEY = {entry["key"]: entry for entry in SETTINGS_SCHEMA}


def config_path(vault: Path | str) -> Path:
    return Path(vault).expanduser().resolve() / ".ai-memory-hub" / CONFIG_FILENAME


def load_config_file(vault: Path | str) -> dict[str, Any]:
    path = config_path(vault)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save_config_file(vault: Path | str, values: dict[str, Any]) -> None:
    path = config_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(values, ensure_ascii=False, indent=2) + "\n")


def bootstrap_environment(vault: Path | str | None) -> None:
    """Seed this process's environment from the vault's config file.

    Best-effort and idempotent: a missing/unreadable file or a falsy vault
    leaves the environment untouched rather than raising, since every caller
    of this (a worker, a hook receiver, the dashboard) must keep starting
    even when configuration is absent or broken.
    """
    if not vault:
        return
    try:
        stored = load_config_file(vault)
    except Exception:
        return
    for key, value in stored.items():
        if key in os.environ:
            continue
        if key not in _BY_KEY:
            continue
        if value in (None, ""):
            continue
        os.environ[key] = str(value)


def normalize_values(values: dict[str, Any]) -> dict[str, Any]:
    """Validate and coerce a POSTed settings payload against the schema.

    Unknown keys are ignored rather than rejected, so a client sending a
    superset (or an older schema) never loses the fields it does understand.
    Raises ValueError naming the offending key on the first invalid value.
    """
    normalized: dict[str, Any] = {}
    for key, raw in values.items():
        entry = _BY_KEY.get(key)
        if entry is None:
            continue
        kind = entry["type"]
        if kind == "bool":
            normalized[key] = bool(raw)
        elif kind == "int":
            try:
                number = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be a whole number") from None
            lo, hi = entry.get("min", 0), entry.get("max", 2**31 - 1)
            if not (lo <= number <= hi):
                raise ValueError(f"{key} must be between {lo} and {hi}")
            normalized[key] = number
        elif kind == "select":
            if raw not in entry["options"]:
                raise ValueError(f"{key} must be one of: {', '.join(entry['options'])}")
            normalized[key] = raw
        else:  # text, password
            normalized[key] = "" if raw is None else str(raw)
    return normalized


def _coerce_for_display(entry: dict[str, Any], raw: Any) -> Any:
    """A bool/int setting must reach the frontend as a real JSON boolean/number,
    never as the raw string an env var (always textual) or a hand-edited
    config.json could hold -- a JS checkbox treats the non-empty string
    "false" as truthy, which would render every such setting checked."""
    kind = entry["type"]
    if kind == "bool":
        return raw if isinstance(raw, bool) else str(raw).strip().lower() in {"1", "true", "yes", "on"}
    if kind == "int":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return entry["default"]
    return raw


def effective_config(vault: Path | str) -> list[dict[str, Any]]:
    """Every schema entry plus its current effective value and where it came
    from ("file", "env", or "default"), for the Settings pane to render."""
    file_values = load_config_file(vault)
    result = []
    for entry in SETTINGS_SCHEMA:
        key = entry["key"]
        if key in file_values and file_values[key] not in (None, ""):
            value, source = _coerce_for_display(entry, file_values[key]), "file"
        elif os.environ.get(key):
            value, source = _coerce_for_display(entry, os.environ[key]), "env"
        else:
            value, source = entry["default"], "default"
        result.append({**entry, "value": value, "source": source})
    return result


def save_settings(vault: Path | str, values: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate, merge into the existing file (a partial payload never wipes
    other keys), persist, and return the new effective_config()."""
    normalized = normalize_values(values)
    merged = {**load_config_file(vault), **normalized}
    save_config_file(vault, merged)
    return effective_config(vault)
