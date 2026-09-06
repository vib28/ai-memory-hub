"""Provider-neutral JSON hook installation with managed-entry backups."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


MANAGED_KEY = "ai_memory_hub_managed"
TOML_MARKER = "# ai-memory-hub managed hook"
CODEX_STATUS_MESSAGE = "AI Memory Hub capture"


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


def install_nested_hook(settings: Path | str, *, event: str, command: str,
                        matcher: str = "*") -> dict[str, Any]:
    """Install a managed Gemini/Qwen-style nested command hook."""
    path = Path(settings).expanduser().resolve()
    config = _load(path)
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise HookConfigError("settings 'hooks' value must be an object")
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        raise HookConfigError(f"settings hook event '{event}' must be an array")
    entry = {"type": "command", "command": command, "name": "ai-memory-hub"}
    # Gemini/Qwen document the nested group shape; keep the marker in the
    # documented hook entry instead of adding an unknown group-level field.
    managed_group = {"matcher": matcher, "hooks": [entry]}
    matches = [i for i, item in enumerate(groups)
               if isinstance(item, dict) and any(
                   isinstance(hook, dict) and hook.get("name") == "ai-memory-hub"
                   for hook in item.get("hooks", [])
               )]
    if len(matches) == 1 and groups[matches[0]] == managed_group:
        return {"status": "already_installed", "settings": str(path), "event": event, "backup": None}
    backup = _backup(path) if path.exists() else None
    if matches:
        groups[matches[0]] = managed_group
        for index in reversed(matches[1:]):
            groups.pop(index)
    else:
        groups.append(managed_group)
    _write(path, config)
    return {"status": "installed", "settings": str(path), "event": event, "backup": backup}


def uninstall_nested_hook(settings: Path | str) -> dict[str, Any]:
    """Remove managed Gemini/Qwen-style nested hook groups only."""
    path = Path(settings).expanduser().resolve()
    if not path.exists():
        return {"status": "not_found", "settings": str(path), "removed": 0, "backup": None}
    config = _load(path)
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        raise HookConfigError("settings 'hooks' value must be an object")
    removed = 0
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        kept = [item for item in groups if not (
            isinstance(item, dict) and any(
                isinstance(hook, dict) and hook.get("name") == "ai-memory-hub"
                for hook in item.get("hooks", [])
            )
        )]
        removed += len(groups) - len(kept)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event)
    if not removed:
        return {"status": "not_found", "settings": str(path), "removed": 0, "backup": None}
    backup = _backup(path)
    _write(path, config)
    return {"status": "removed", "settings": str(path), "removed": removed, "backup": backup}


def install_codex_hook(settings: Path | str, *, event: str, command: str,
                       matcher: str = "*") -> dict[str, Any]:
    """Install a Codex hook using only documented handler fields."""
    path = Path(settings).expanduser().resolve()
    config = _load(path)
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise HookConfigError("settings 'hooks' value must be an object")
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        raise HookConfigError(f"settings hook event '{event}' must be an array")
    entry = {"type": "command", "command": command, "statusMessage": CODEX_STATUS_MESSAGE}
    managed_group = {"matcher": matcher, "hooks": [entry]}

    def is_managed(item: Any) -> bool:
        return isinstance(item, dict) and any(
            isinstance(hook, dict)
            and hook.get("type") == "command"
            and hook.get("command") == command
            and hook.get("statusMessage") == CODEX_STATUS_MESSAGE
            for hook in item.get("hooks", [])
        )

    matches = [index for index, item in enumerate(groups) if is_managed(item)]
    if len(matches) == 1 and groups[matches[0]] == managed_group:
        return {"status": "already_installed", "settings": str(path), "event": event, "backup": None}
    if len(matches) > 1:
        raise HookConfigError("multiple managed Codex hook groups found")
    backup = _backup(path) if path.exists() else None
    if matches:
        groups[matches[0]] = managed_group
    else:
        groups.append(managed_group)
    _write(path, config)
    return {"status": "installed", "settings": str(path), "event": event, "backup": backup}


def uninstall_codex_hook(settings: Path | str, *, command: str) -> dict[str, Any]:
    """Remove only the Codex handler identified by its documented marker."""
    path = Path(settings).expanduser().resolve()
    if not path.exists():
        return {"status": "not_found", "settings": str(path), "removed": 0, "backup": None}
    config = _load(path)
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        raise HookConfigError("settings 'hooks' value must be an object")
    removed = 0
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                kept_groups.append(group)
                continue
            kept_handlers = [handler for handler in group["hooks"] if not (
                isinstance(handler, dict)
                and handler.get("type") == "command"
                and handler.get("command") == command
                and handler.get("statusMessage") == CODEX_STATUS_MESSAGE
            )]
            removed += len(group["hooks"]) - len(kept_handlers)
            if kept_handlers:
                group["hooks"] = kept_handlers
                kept_groups.append(group)
            elif len(group["hooks"]) == 0:
                kept_groups.append(group)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            hooks.pop(event)
    if not removed:
        return {"status": "not_found", "settings": str(path), "removed": 0, "backup": None}
    backup = _backup(path)
    _write(path, config)
    return {"status": "removed", "settings": str(path), "removed": removed, "backup": backup}


def _toml_managed_ranges(content: str) -> list[tuple[int, int]]:
    """Return exact managed block ranges without parsing/reformatting TOML."""
    lines = content.splitlines(keepends=True)
    ranges: list[tuple[int, int]] = []
    offset = 0
    for index, line in enumerate(lines):
        if line.rstrip("\r\n") != TOML_MARKER:
            offset += len(line)
            continue
        if index + 3 >= len(lines):
            raise HookConfigError("managed Kimi hook marker is incomplete")
        table, event, command = lines[index + 1:index + 4]
        if table.rstrip("\r\n") != "[[hooks]]" or not event.startswith("event = ") or not command.startswith("command = "):
            raise HookConfigError("managed Kimi hook marker has an unexpected TOML shape")
        end = offset + sum(len(item) for item in lines[index:index + 4])
        ranges.append((offset, end))
        offset += len(line)
    return ranges


def _toml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def install_toml_hook(settings: Path | str, *, event: str, command: str) -> dict[str, Any]:
    """Install a marked Kimi-style TOML hook while preserving source text."""
    path = Path(settings).expanduser().resolve()
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    ranges = _toml_managed_ranges(content)
    desired = (
        f"{TOML_MARKER}\n[[hooks]]\nevent = {_toml_quote(event)}\n"
        f"command = {_toml_quote(command)}\n"
    )
    if len(ranges) == 1 and content[ranges[0][0]:ranges[0][1]] == desired:
        return {"status": "already_installed", "settings": str(path), "event": event, "backup": None}
    if len(ranges) > 1:
        raise HookConfigError("multiple managed Kimi hook blocks found")
    backup = _backup(path) if path.exists() else None
    if ranges:
        start, end = ranges[0]
        updated = content[:start] + desired + content[end:]
    else:
        separator = "" if not content else ("" if content.endswith("\n") else "\n")
        if content and not content.endswith("\n\n"):
            separator += "\n"
        updated = content + separator + desired
    _write_text(path, updated)
    return {"status": "installed", "settings": str(path), "event": event, "backup": backup}


def uninstall_toml_hook(settings: Path | str) -> dict[str, Any]:
    """Remove only the marked Kimi-style TOML hook block."""
    path = Path(settings).expanduser().resolve()
    if not path.exists():
        return {"status": "not_found", "settings": str(path), "removed": 0, "backup": None}
    content = path.read_text(encoding="utf-8")
    ranges = _toml_managed_ranges(content)
    if not ranges:
        return {"status": "not_found", "settings": str(path), "removed": 0, "backup": None}
    if len(ranges) > 1:
        raise HookConfigError("multiple managed Kimi hook blocks found")
    start, end = ranges[0]
    backup = _backup(path)
    _write_text(path, content[:start] + content[end:])
    return {"status": "removed", "settings": str(path), "removed": 1, "backup": backup}
