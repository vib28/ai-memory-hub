"""Opt-in Git history for automated vault changes."""

from __future__ import annotations

import subprocess
from pathlib import Path


GITIGNORE_ENTRIES = (
    ".memory_index.sqlite3",
    ".memory_index.sqlite3-wal",
    ".memory_index.sqlite3-shm",
    "*.lock",
    "*.tmp",
)


class VaultHistoryError(RuntimeError):
    pass


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise VaultHistoryError(f"git is not available: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise VaultHistoryError(detail or f"git {' '.join(args)} failed")
    return result


def is_git_repository(root: Path | str) -> bool:
    path = Path(root).expanduser().resolve()
    result = _git(path, "rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _ensure_gitignore(root: Path) -> bool:
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = existing.splitlines()
    changed = False
    for entry in GITIGNORE_ENTRIES:
        if entry not in lines:
            lines.append(entry)
            changed = True
    if changed:
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return changed


def initialize_history(root: Path | str) -> dict:
    path = Path(root).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    already = is_git_repository(path)
    if not already:
        _git(path, "init")
    ignore_changed = _ensure_gitignore(path)
    _git(path, "config", "user.name", "AI Memory Hub")
    _git(path, "config", "user.email", "ai-memory-hub@localhost")
    baseline_commit = None
    if not already:
        _git(path, "add", "-A")
        staged = _git(path, "diff", "--cached", "--name-only").stdout.splitlines()
        if staged:
            message = "ai-memory: initialize vault history"
            _git(path, "commit", "-m", message)
            baseline_commit = message
    status = _git(path, "status", "--porcelain", check=False).stdout.splitlines()
    return {
        "status": "already_initialized" if already else "initialized",
        "path": str(path),
        "gitignore_updated": ignore_changed,
        "baseline_commit": baseline_commit,
        "pending_changes": len(status),
    }


def commit_vault_change(root: Path | str, session_id: str, relative_paths: list[str]) -> dict:
    path = Path(root).expanduser().resolve()
    if not is_git_repository(path):
        return {"status": "disabled", "reason": "vault history is not initialized"}
    safe_paths: list[str] = []
    for relative in relative_paths:
        candidate = (path / relative.lstrip("/\\")).resolve()
        if candidate != path and path not in candidate.parents:
            raise VaultHistoryError(f"path escapes vault: {relative}")
        if candidate.exists():
            candidate_relative = candidate.relative_to(path).as_posix()
            ignored = _git(path, "check-ignore", "--quiet", "--", candidate_relative, check=False)
            if ignored.returncode != 0:
                safe_paths.append(candidate_relative)
    if not safe_paths:
        return {"status": "nothing_to_commit", "session_id": session_id}
    pre_staged = _git(path, "diff", "--cached", "--name-only").stdout.splitlines()
    if pre_staged:
        raise VaultHistoryError(
            "vault has pre-staged changes; automated history commit refused to mix them: "
            + ", ".join(pre_staged)
        )
    _git(path, "add", "--", *safe_paths)
    staged = _git(path, "diff", "--cached", "--name-only").stdout.splitlines()
    if not staged:
        return {"status": "nothing_to_commit", "session_id": session_id}
    message = f"ai-memory: consolidate session {session_id}"
    result = _git(path, "commit", "-m", message, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise VaultHistoryError(detail or "git commit failed")
    return {"status": "committed", "session_id": session_id, "paths": staged, "message": message}


def history_status(root: Path | str) -> dict:
    path = Path(root).expanduser().resolve()
    if not is_git_repository(path):
        return {"enabled": False, "path": str(path)}
    result = _git(path, "log", "-1", "--format=%H%x09%s", check=False)
    latest = result.stdout.strip().split("\t", 1) if result.stdout.strip() else []
    return {
        "enabled": True,
        "path": str(path),
        "clean": not bool(_git(path, "status", "--porcelain", check=False).stdout.strip()),
        "latest_commit": latest[0] if latest else None,
        "latest_message": latest[1] if len(latest) > 1 else None,
    }
