from __future__ import annotations

import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "general"

def normalize_text(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"[^\w\s]", "", value)
    return value

def text_hash(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()

def safe_join(root: Path, relative: str) -> Path:
    relative = relative.replace("\\", "/").lstrip("/")
    target = (root / relative).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError("target path escapes vault")
    return target

def _read_lock_pid(lock: Path) -> int | None:
    try:
        content = lock.read_text(encoding="ascii").strip()
        return int(content) if content else None
    except (FileNotFoundError, ValueError, OSError):
        return None

def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        import ctypes.wintypes as wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # ERROR_ACCESS_DENIED (5) still means a live process we can't query.
            return ctypes.get_last_error() == 5
        try:
            # A terminated process stays queryable (as a "zombie") for as long as
            # any handle to it is open elsewhere, so a successful OpenProcess alone
            # doesn't mean "running" — check the exit code too: STILL_ACTIVE (259)
            # is the only value that means it hasn't actually exited.
            STILL_ACTIVE = 259
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

@contextmanager
def file_lock(target: Path, timeout: float = 8.0, poll: float = 0.05):
    """Cooperative lock via an exclusively-created sidecar file holding the
    owner's PID. A lock left behind by a killed process is detected (the PID
    is dead) and stolen instead of blocking every future writer forever."""
    lock = target.with_suffix(target.suffix + ".lock")
    deadline = time.monotonic() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
        except FileExistsError:
            stale_pid = _read_lock_pid(lock)
            if stale_pid is not None and not _pid_alive(stale_pid):
                # Steal via an atomic rename, not a plain unlink: two waiters can
                # both observe the same dead PID, and an unconditional unlink lets
                # both proceed to os.open() the fresh lock the other just created,
                # putting them in the critical section together. os.replace is a
                # single winner per source path — a loser gets FileNotFoundError
                # and simply retries instead of deleting a lock it doesn't own.
                stolen = lock.with_name(lock.name + f".stale-{os.getpid()}")
                try:
                    os.replace(str(lock), str(stolen))
                except FileNotFoundError:
                    continue
                try:
                    stolen.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for lock: {lock}")
            time.sleep(poll)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock.unlink()
        except FileNotFoundError:
            pass

def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Restrict tmp to owner-only before write so secrets are never world-readable
    # on the transient file (#169).
    fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, path)


def parse_iso_datetime(value: Any, fallback: datetime | None = None) -> datetime | None:
    """Parse an ISO-8601 datetime string, normalizing ``Z`` suffixes and
    assigning UTC when no offset is present.

    Returns ``fallback`` (or ``None`` if not given) when ``value`` is falsy or
    unparseable.
    """
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


_TRUTHY_STRINGS = frozenset({"1", "true", "yes", "on"})


def truncated_text(value: Any, maximum: int = 500) -> str:
    """Truncate ``value`` to ``maximum`` chars after stripping."""
    return str(value).strip()[:maximum] if value is not None else ""


def clean_list(value: Any, *, limit: int = 30, truncate: int = 1000,
                transform: Any = None) -> list[str]:
    """Coerce ``value`` to a cleaned, capped list of strings.

    - Non-list inputs return ``[]``.
    - Each item is transformed (via ``transform`` if given, else
      ``str(item).strip()[:truncate]``); blank results are dropped.
    - Result is capped at ``limit`` entries.
    """
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if transform is not None:
            text = transform(item)
        else:
            text = str(item).strip()[:truncate]
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def one_line(value: Any, limit: int = 1000) -> str:
    """Coerce any value to a single-line string, replacing null bytes,
    collapsing internal whitespace, and truncating to ``limit`` chars."""
    return " ".join(str(value or "").replace("\x00", " ").split())[:limit]


def is_truthy(value: Any) -> bool:
    """Return True for ``value`` that reads as an affirmative flag.

    A ``bool`` is returned as-is; any other value is stringified, stripped,
    lowercased, and matched against ``{"1", "true", "yes", "on"}``.
    """
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in _TRUTHY_STRINGS


# --------------------------------------------------------------------------- JSON
# Helpers used across the codebase to read/write JSON files atomically.

def read_json(path: Path, default: Any = None, *, encoding: str = "utf-8") -> Any:
    """Read and parse a JSON file, returning ``default`` if missing or unreadable.

    Handles ``OSError`` (missing file, permission errors) and
    ``json.JSONDecodeError`` (corrupt file) gracefully -- callers that need
    distinct handling for "missing" vs "corrupt" should read the file directly.
    """
    try:
        return json.loads(path.read_text(encoding=encoding))
    except (OSError, json.JSONDecodeError):
        return default


def vault_key(vault: Path | str, length: int = 16) -> str:
    """Return a stable, collision-resistant key for a vault path.

    Used to generate per-vault file names (health JSON, outbox DB, export
    config, ...) that stay unique per vault without leaking the vault's location.
    """
    return hashlib.sha256(
        str(Path(vault).expanduser().resolve()).encode("utf-8")
    ).hexdigest()[:length]
