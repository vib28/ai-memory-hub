"""Provider-neutral JSON hook installation with managed-entry backups."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


MANAGED_KEY = "ai_memory_hub_managed"
TOML_MARKER = "# ai-memory-hub managed hook"
CODEX_STATUS_MESSAGE = "AI Memory Hub capture"
CODEX_STATUS_CONTEXT = "AI Memory Hub context"


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


def _claude_managed(handler: Any, command: str | None = None) -> bool:
    return (isinstance(handler, dict) and handler.get(MANAGED_KEY)
            and (command is None or handler.get("command") == command))


def install_claude_hook(settings: Path | str, *, event: str, command: str,
                        matcher: str = "*", args: list[str] | None = None) -> dict[str, Any]:
    """Install a Claude nested matcher group without disturbing sibling handlers.

    Capture and context are different commands, so one event may own two managed
    handlers (#86). Matching is by command; unrelated managed handlers stay.
    """
    path = Path(settings).expanduser().resolve()
    config = _load(path)
    groups = _hook_list(config, event)
    managed = {"type": "command", "command": command, "args": list(args or []), MANAGED_KEY: True}
    found_group = None
    found_index = None
    for group in groups:
        if not isinstance(group, dict):
            continue
        for index, handler in enumerate(group.get("hooks", [])):
            if _claude_managed(handler, command):
                found_group, found_index = group, index
                break
        if found_group is not None:
            break
    if found_group is not None and found_group["hooks"][found_index] == managed:
        return {"status": "already_installed", "settings": str(path), "event": event, "backup": None}
    backup = _backup(path) if path.exists() else None
    if found_group is not None:
        found_group["hooks"][found_index] = managed
    else:
        star = next((group for group in groups
                     if isinstance(group, dict) and group.get("matcher", matcher) == matcher), None)
        if star is not None:
            star.setdefault("hooks", []).append(managed)
        else:
            groups.append({"matcher": matcher, "hooks": [managed]})
    _write(path, config)
    return {"status": "installed", "settings": str(path), "event": event, "backup": backup}


def uninstall_claude_hook(settings: Path | str, *, command: str | None = None) -> dict[str, Any]:
    """Remove nested Claude managed handlers, optionally limited to ``command``."""
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
            kept = [handler for handler in group["hooks"] if not _claude_managed(handler, command)]
            removed += len(group["hooks"]) - len(kept)
            if kept:
                group["hooks"] = kept
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


def uninstall_hook(settings: Path | str, *, command: str | None = None) -> dict[str, Any]:
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
        kept = [item for item in values if not (
            isinstance(item, dict) and item.get(MANAGED_KEY)
            and (command is None or item.get("command") == command)
        )]
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
    """Install a managed Gemini/Qwen-style nested command hook.

    Capture and context are different commands, so one event may own two managed
    handlers (#86). Matching is by command.
    """
    path = Path(settings).expanduser().resolve()
    config = _load(path)
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise HookConfigError("settings 'hooks' value must be an object")
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        raise HookConfigError(f"settings hook event '{event}' must be an array")
    name = "ai-memory-hub-context" if "ai-memory-context" in command or "ai-memory-handoff" in command else "ai-memory-hub"
    entry = {"type": "command", "command": command, "name": name}

    def ours(hook: Any) -> bool:
        return (isinstance(hook, dict) and hook.get("command") == command
                and str(hook.get("name", "")).startswith("ai-memory-hub"))

    found_group = None
    found_index = None
    for group in groups:
        if not isinstance(group, dict):
            continue
        for index, hook in enumerate(group.get("hooks", [])):
            if ours(hook):
                found_group, found_index = group, index
                break
        if found_group is not None:
            break
    if found_group is not None and found_group["hooks"][found_index] == entry:
        return {"status": "already_installed", "settings": str(path), "event": event, "backup": None}
    backup = _backup(path) if path.exists() else None
    if found_group is not None:
        found_group["hooks"][found_index] = entry
    else:
        star = next((group for group in groups
                     if isinstance(group, dict) and group.get("matcher", matcher) == matcher), None)
        if star is not None:
            star.setdefault("hooks", []).append(entry)
        else:
            groups.append({"matcher": matcher, "hooks": [entry]})
    _write(path, config)
    return {"status": "installed", "settings": str(path), "event": event, "backup": backup}


def uninstall_nested_hook(settings: Path | str, *, command: str | None = None) -> dict[str, Any]:
    """Remove managed Gemini/Qwen-style nested hook handlers."""
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
        kept = []
        for item in groups:
            if not isinstance(item, dict) or not isinstance(item.get("hooks"), list):
                kept.append(item)
                continue
            handlers = item["hooks"]
            remaining = [hook for hook in handlers if not (
                isinstance(hook, dict) and str(hook.get("name", "")).startswith("ai-memory-hub")
                and (command is None or hook.get("command") == command
                     or str(hook.get("command", "")).startswith(str(command)))
            )]
            removed += len(handlers) - len(remaining)
            if remaining:
                item["hooks"] = remaining
                kept.append(item)
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
                       matcher: str = "*", additional_context_limit: int | None = None) -> dict[str, Any]:
    """Install a Codex hook using only documented handler fields.

    Capture and context are different commands, so one event may own two managed
    handlers (#86). Matching is by command.
    """
    path = Path(settings).expanduser().resolve()
    config = _load(path)
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise HookConfigError("settings 'hooks' value must be an object")
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        raise HookConfigError(f"settings hook event '{event}' must be an array")
    status = CODEX_STATUS_CONTEXT if additional_context_limit is not None else CODEX_STATUS_MESSAGE
    entry = {"type": "command", "command": command, "statusMessage": status}
    if additional_context_limit is not None:
        entry["additionalContextLimit"] = max(0, int(additional_context_limit))

    def ours(hook: Any) -> bool:
        return (isinstance(hook, dict) and hook.get("type") == "command"
                and hook.get("command") == command
                and str(hook.get("statusMessage", "")).startswith("AI Memory Hub"))

    found_group = None
    found_index = None
    for group in groups:
        if not isinstance(group, dict):
            continue
        for index, hook in enumerate(group.get("hooks", [])):
            if ours(hook):
                found_group, found_index = group, index
                break
        if found_group is not None:
            break
    if found_group is not None and found_group["hooks"][found_index] == entry:
        return {"status": "already_installed", "settings": str(path), "event": event, "backup": None}
    backup = _backup(path) if path.exists() else None
    if found_group is not None:
        found_group["hooks"][found_index] = entry
    else:
        star = next((group for group in groups
                     if isinstance(group, dict) and group.get("matcher", matcher) == matcher), None)
        if star is not None:
            star.setdefault("hooks", []).append(entry)
        else:
            groups.append({"matcher": matcher, "hooks": [entry]})
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
                and str(handler.get("statusMessage", "")).startswith("AI Memory Hub")
            )]
            removed += len(group["hooks"]) - len(kept_handlers)
            if kept_handlers:
                group["hooks"] = kept_handlers
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
    """Return exact managed block ranges without parsing/reformatting TOML.

    A managed block is the marker line followed by ``[[hooks]]``, ``event = ...``
    and ``command = ...``, optionally followed by ``matcher = ...`` and/or
    ``timeout = ...`` lines that this project also owns (#86).
    """
    lines = content.splitlines(keepends=True)
    ranges: list[tuple[int, int]] = []
    offset = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.rstrip("\r\n") != TOML_MARKER:
            offset += len(line)
            index += 1
            continue
        if index + 3 >= len(lines):
            raise HookConfigError("managed Kimi hook marker is incomplete")
        table, event, command = lines[index + 1:index + 4]
        if table.rstrip("\r\n") != "[[hooks]]" or not event.startswith("event = ") or not command.startswith("command = "):
            raise HookConfigError("managed Kimi hook marker has an unexpected TOML shape")
        length = 4
        while index + length < len(lines) and re.match(r"^(matcher|timeout) = ", lines[index + length]):
            length += 1
        end = offset + sum(len(item) for item in lines[index:index + length])
        ranges.append((offset, end))
        offset = end
        index += length
    return ranges


def _toml_block_event(content: str, block: tuple[int, int]) -> str:
    match = re.search(r'^event = "(?P<event>[^"]*)"', content[block[0]:block[1]], re.MULTILINE)
    return match.group("event") if match else ""


def _toml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def install_toml_hook(settings: Path | str, *, event: str, command: str,
                      matcher: str | None = None, timeout: int | None = None) -> dict[str, Any]:
    """Install a marked Kimi-style TOML hook while preserving source text.

    One managed block per *event*: installing a second event appends a second
    marked block; re-installing the same event replaces only its own block (#86).
    Kimi's ``[[hooks]]`` accepts exactly ``event``/``matcher``/``command``/``timeout``.
    """
    path = Path(settings).expanduser().resolve()
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    ranges = _toml_managed_ranges(content)
    desired = (
        f"{TOML_MARKER}\n[[hooks]]\nevent = {_toml_quote(event)}\n"
        f"command = {_toml_quote(command)}\n"
    )
    if matcher is not None:
        desired += f"matcher = {_toml_quote(matcher)}\n"
    if timeout is not None:
        desired += f"timeout = {max(1, min(int(timeout), 600))}\n"
    same_event = [block for block in ranges if _toml_block_event(content, block) == event]
    if len(same_event) > 1:
        raise HookConfigError(f"multiple managed Kimi hook blocks found for {event}")
    if same_event and content[same_event[0][0]:same_event[0][1]] == desired:
        return {"status": "already_installed", "settings": str(path), "event": event, "backup": None}
    backup = _backup(path) if path.exists() else None
    if same_event:
        start, end = same_event[0]
        updated = content[:start] + desired + content[end:]
    else:
        separator = "" if not content else ("" if content.endswith("\n") else "\n")
        if content and not content.endswith("\n\n"):
            separator += "\n"
        updated = content + separator + desired
    _write_text(path, updated)
    return {"status": "installed", "settings": str(path), "event": event, "backup": backup}


def uninstall_toml_hook(settings: Path | str, *, command: str | None = None) -> dict[str, Any]:
    """Remove the marked Kimi-style TOML hook blocks (all, or only those running ``command``)."""
    path = Path(settings).expanduser().resolve()
    if not path.exists():
        return {"status": "not_found", "settings": str(path), "removed": 0, "backup": None}
    content = path.read_text(encoding="utf-8")
    ranges = _toml_managed_ranges(content)
    if command is not None:
        quoted = f"command = {_toml_quote(command)}"
        ranges = [block for block in ranges if quoted in content[block[0]:block[1]]]
    if not ranges:
        return {"status": "not_found", "settings": str(path), "removed": 0, "backup": None}
    backup = _backup(path)
    for start, end in sorted(ranges, reverse=True):
        content = content[:start] + content[end:]
    _write_text(path, content)
    return {"status": "removed", "settings": str(path), "removed": len(ranges), "backup": backup}


# ------------------------------------------------------------------ Hermes YAML

HERMES_MARKER = "# ai-memory-hub managed hook"


def _hermes_load(path: Path) -> dict[str, Any]:
    """Load a Hermes profile config.yaml without a YAML dependency for the write path.

    We need round-tripping that preserves the user's file byte-for-byte outside
    the managed entries, so the *edit* is textual: the managed entry is a
    fenced, marker-commented block under ``hooks:``.  Parsing for status uses
    PyYAML when available and a conservative regex otherwise.
    """
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - depends on user file
        raise HookConfigError(f"config.yaml is invalid: {exc}") from exc
    return value if isinstance(value, dict) else {}


_HERMES_BLOCK_RE = re.compile(
    r"^(?P<indent>[ \t]*)" + re.escape(HERMES_MARKER) + r" event=(?P<event>[a-z_]+)\n"
    r"(?P=indent)- command: (?P<command>[^\n]*)\n"
    r"(?:(?P=indent)  [a-z_]+: [^\n]*\n)*",
    re.MULTILINE,
)


def install_hermes_hook(config_yaml: Path | str, *, event: str, command: str,
                        timeout: int = 20, matcher: str | None = None) -> dict[str, Any]:
    """Install a managed shell hook into a Hermes profile ``config.yaml`` (#86).

    Hermes shell hooks live under a top-level ``hooks:`` map keyed by event
    (``pre_llm_call``, ``on_session_start``, ``post_tool_call``, ...), each a list
    of ``{command, timeout, matcher}`` entries.  The edit is textual and marker
    fenced so the rest of the user's YAML is untouched; siblings under the same
    event are preserved.  The user still has to approve the hook once in Hermes
    (its consent model) unless ``hooks_auto_accept`` is set -- this installer
    never sets that flag.
    """
    path = Path(config_yaml).expanduser().resolve()
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    entry_lines = [f"  {HERMES_MARKER} event={event}", f"  - command: {json.dumps(command)}",
                   f"    timeout: {max(1, min(int(timeout), 300))}"]
    if matcher:
        entry_lines.append(f"    matcher: {json.dumps(matcher)}")
    entry = "\n".join(entry_lines) + "\n"

    existing = [m for m in _HERMES_BLOCK_RE.finditer(content) if m.group("event") == event
                and json.loads(m.group("command").strip()) == command]
    if len(existing) > 1:
        raise HookConfigError("multiple managed Hermes hook entries found")
    if existing:
        current = content[existing[0].start():existing[0].end()]
        # Normalise indentation to compare the payload only.
        if "\n".join(line.strip() for line in current.splitlines()) == \
                "\n".join(line.strip() for line in entry.splitlines()):
            return {"status": "already_installed", "settings": str(path), "event": event, "backup": None}
    backup = _backup(path) if path.exists() else None
    if existing:
        updated = content[:existing[0].start()] + entry + content[existing[0].end():]
        _write_text(path, updated)
        return {"status": "installed", "settings": str(path), "event": event, "backup": backup}

    lines = content.splitlines(keepends=True)
    hooks_index = next((i for i, line in enumerate(lines) if re.match(r"^hooks:\s*$", line)), None)
    if hooks_index is None:
        separator = "" if not content or content.endswith("\n") else "\n"
        updated = content + separator + ("\n" if content else "") + "hooks:\n" + f"  {event}:\n" + \
            "\n".join("  " + line if line.strip() else line for line in entry.splitlines()) + "\n"
        _write_text(path, updated)
        return {"status": "installed", "settings": str(path), "event": event, "backup": backup}
    # Find the end of the hooks: mapping (next top-level key or EOF).
    end = len(lines)
    for i in range(hooks_index + 1, len(lines)):
        if lines[i].strip() and not lines[i].startswith((" ", "\t", "#")):
            end = i
            break
    event_index = next((i for i in range(hooks_index + 1, end)
                        if re.match(rf"^  {re.escape(event)}:\s*$", lines[i])), None)
    indented_entry = "".join("  " + line if line.strip() else line
                             for line in entry.splitlines(keepends=True))
    if event_index is None:
        insert_at = end
        block = f"  {event}:\n" + indented_entry
    else:
        insert_at = end
        for i in range(event_index + 1, end):
            if re.match(r"^  [a-z_]+:\s*$", lines[i]):
                insert_at = i
                break
        block = indented_entry
    lines[insert_at:insert_at] = [block]
    _write_text(path, "".join(lines))
    return {"status": "installed", "settings": str(path), "event": event, "backup": backup}


def uninstall_hermes_hook(config_yaml: Path | str, *, command: str | None = None) -> dict[str, Any]:
    """Remove managed Hermes hook entries (all, or only those running ``command``)."""
    path = Path(config_yaml).expanduser().resolve()
    if not path.exists():
        return {"status": "not_found", "settings": str(path), "removed": 0, "backup": None}
    content = path.read_text(encoding="utf-8")
    matches = list(_HERMES_BLOCK_RE.finditer(content))
    if command is not None:
        matches = [m for m in matches if json.loads(m.group("command").strip()) == command]
    if not matches:
        return {"status": "not_found", "settings": str(path), "removed": 0, "backup": None}
    backup = _backup(path)
    for match in sorted(matches, key=lambda m: m.start(), reverse=True):
        content = content[:match.start()] + content[match.end():]
    # Drop now-empty "  <event>:" headers and an empty "hooks:" map.
    content = re.sub(r"^  [a-z_]+:\s*\n(?=  [a-z_]+:\s*\n|(?![ \t]))", "", content, flags=re.MULTILINE)
    content = re.sub(r"^hooks:\s*\n(?![ \t])", "", content, flags=re.MULTILINE)
    _write_text(path, content)
    return {"status": "removed", "settings": str(path), "removed": len(matches), "backup": backup}
