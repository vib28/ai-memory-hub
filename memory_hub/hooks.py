"""Provider-neutral JSON hook installation with managed-entry backups."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


MANAGED_KEY = "ai_memory_hub_managed"


class HookConfigError(RuntimeError):
    pass


def _backup(path: Path) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    destination = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, destination)
    return str(destination)


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        backup = _backup(path)
        raise HookConfigError(f"settings JSON is invalid; backup created at {backup}") from exc
    if not isinstance(value, dict):
        raise HookConfigError("settings JSON must contain an object at the top level")
    return value


def _write(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _hook_list(config: dict[str, Any], event: str) -> list[Any]:
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise HookConfigError("settings 'hooks' value must be an object")
    current = hooks.setdefault(event, [])
    if not isinstance(current, list):
        raise HookConfigError(f"settings hook event '{event}' must be an array")
    return current


def install_hook(settings: Path | str, *, event: str, command: str, args: list[str] | None = None) -> dict[str, Any]:
    path = Path(settings).expanduser().resolve()
    config = _load(path)
    hooks = _hook_list(config, event)
    entry = {
        "type": "command",
        "command": command,
        "args": list(args or []),
        MANAGED_KEY: True,
    }
    matches = [index for index, item in enumerate(hooks) if isinstance(item, dict) and item.get(MANAGED_KEY)]
    changed = False
    if len(matches) == 1 and hooks[matches[0]] == entry:
        return {"status": "already_installed", "settings": str(path), "event": event, "backup": None}
    backup = _backup(path) if path.exists() else None
    if matches:
        hooks[matches[0]] = entry
        for index in reversed(matches[1:]):
            hooks.pop(index)
    else:
        hooks.append(entry)
    changed = True
    _write(path, config)
    return {"status": "installed" if changed else "already_installed", "settings": str(path), "event": event, "backup": backup}


def uninstall_hook(settings: Path | str) -> dict[str, Any]:
    path = Path(settings).expanduser().resolve()
    if not path.exists():
        return {"status": "not_found", "settings": str(path), "removed": 0, "backup": None}
    config = _load(path)
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        raise HookConfigError("settings 'hooks' value must be an object")
    removed = 0
    for event, values in list(hooks.items()):
        if not isinstance(values, list):
            continue
        kept = [item for item in values if not (isinstance(item, dict) and item.get(MANAGED_KEY))]
        removed += len(values) - len(kept)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event)
    if not removed:
        return {"status": "not_found", "settings": str(path), "removed": 0, "backup": None}
    backup = _backup(path)
    _write(path, config)
    return {"status": "removed", "settings": str(path), "removed": removed, "backup": backup}
