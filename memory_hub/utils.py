from __future__ import annotations

import hashlib
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

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
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
