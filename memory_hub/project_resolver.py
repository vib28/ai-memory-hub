"""Deterministic project identity from a working directory (#84).

Every stage of the automatic pipeline -- capture, checkpointing, categorization,
handoff and MCP context -- has to agree on *which project* a piece of evidence
belongs to.  Hooks only give us ``cwd``; connected models are unreliable at
spelling a project name; and the continuity design forbids resolving identity
from embeddings, title prefixes or credential-bearing remote URLs.

Resolution order (first hit wins):

1. ``<vault>/.ai-memory-hub/projects.json`` -- an explicit ``{"<path>": "<slug>"}``
   map.  The longest matching path prefix wins, so a nested override beats an
   outer one.
2. A ``.ai-memory-project`` file at the detected root containing the canonical
   slug (lets a repository pin its own identity in-tree).
3. The nearest ancestor containing ``.git`` (a *file* for linked worktrees, a
   directory otherwise).  For a worktree the identity is the main repository's
   directory name, read from the ``gitdir:`` pointer, so all worktrees of one
   repository share one project.
4. The nearest ancestor containing a build/package marker.
5. The ``cwd`` leaf directory itself.

Paths that are not a project at all -- the user's home directory, system
directories, drive roots -- resolve to the reserved ``unscoped`` project so
unrelated shell sessions are never merged with real work.  Nothing here shells
out to ``git`` or touches the network; the resolver must stay safe to call from a
hook that has a sub-second budget.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from .utils import slugify


UNSCOPED = "unscoped"
OVERRIDES_FILENAME = "projects.json"
PIN_FILENAME = ".ai-memory-project"

# A cwd whose root is one of these is not a project. Names are compared on the
# normalized last path component of the *resolved root*, so a real repository that
# happens to live under Documents is unaffected.
_NON_PROJECT_LEAVES = {
    "", "users", "home", "system32", "windows", "documents", "desktop", "downloads",
    "onedrive", "projects", "src", "code", "repos", "dev", "tmp", "temp", "program files",
    "program files (x86)", "appdata", "local", "roaming",
}

_PACKAGE_MARKERS = (
    "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
    "build.gradle.kts", "composer.json", "Gemfile", "mix.exs", "CMakeLists.txt", "Makefile",
    "setup.py", "deno.json", "pubspec.yaml",
)
_SOLUTION_GLOBS = ("*.sln", "*.csproj", "*.xcodeproj")


@dataclass(frozen=True)
class ProjectIdentity:
    project: str
    worktree: str | None
    source: str  # override | pin | git | marker | cwd | unscoped

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize(path: str | os.PathLike[str]) -> Path:
    text = str(path).strip().strip('"')
    if not text:
        return Path()
    try:
        return Path(text).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return Path(text)


def _key(path: Path) -> str:
    return os.path.normcase(str(path).replace("\\", "/").rstrip("/"))


def _read_gitdir_pointer(git_file: Path) -> Path | None:
    """Linked worktrees store ``gitdir: <main>/.git/worktrees/<name>`` in a file."""
    try:
        content = git_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"^gitdir:\s*(?P<target>.+?)\s*$", content, re.MULTILINE)
    if not match:
        return None
    target = Path(match.group("target").strip())
    if not target.is_absolute():
        target = git_file.parent / target
    target = _normalize(target)
    # <main>/.git/worktrees/<name>  ->  <main>
    parts = [part.lower() for part in target.parts]
    if "worktrees" in parts:
        index = len(parts) - 1 - parts[::-1].index("worktrees")
        if index >= 1 and parts[index - 1] == ".git":
            return Path(*target.parts[:index - 1])
    return None


def _git_root(start: Path) -> tuple[Path, Path] | None:
    """Return ``(worktree_root, identity_root)`` for the nearest ``.git``."""
    for candidate in (start, *start.parents):
        marker = candidate / ".git"
        if marker.is_dir():
            return candidate, candidate
        if marker.is_file():
            main = _read_gitdir_pointer(marker)
            return candidate, (main or candidate)
    return None


def _marker_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if any((candidate / name).exists() for name in _PACKAGE_MARKERS):
            return candidate
        for pattern in _SOLUTION_GLOBS:
            try:
                if next(candidate.glob(pattern), None) is not None:
                    return candidate
            except OSError:
                continue
    return None


def _is_home_or_system(path: Path) -> bool:
    """The cwd itself is the user's home, a drive root or an OS directory."""
    if path.parent == path:
        return True
    try:
        if path == Path.home().resolve(strict=False):
            return True
    except (OSError, RuntimeError):
        pass
    lowered = _key(path)
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if system_root and lowered.startswith(_key(_normalize(system_root))):
        return True
    return lowered in {"/usr", "/etc", "/bin", "/tmp", "/var", "/opt", "/proc"} or lowered.startswith(
        ("/usr/", "/etc/", "/bin/", "/proc/"))


def _looks_unscoped(root: Path) -> bool:
    leaf = root.name.lower()
    if leaf in _NON_PROJECT_LEAVES:
        return True
    return _is_home_or_system(root)


def load_overrides(vault: Path | str | None) -> dict[str, str]:
    if not vault:
        return {}
    path = Path(vault).expanduser() / ".ai-memory-hub" / OVERRIDES_FILENAME
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {_key(_normalize(k)): slugify(str(v)) for k, v in value.items()
            if isinstance(k, str) and isinstance(v, str) and slugify(str(v)) != "general"}


def _pinned(root: Path) -> str | None:
    pin = root / PIN_FILENAME
    if not pin.is_file():
        return None
    try:
        text = pin.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return None
    for line in text:
        line = line.strip()
        if line and not line.startswith("#"):
            slug = slugify(line)
            return slug if slug != "general" else None
    return None


def resolve_project(cwd: str | os.PathLike[str] | None, *, vault: Path | str | None = None,
                    explicit: str | None = None) -> ProjectIdentity:
    """Resolve a stable project identity for ``cwd``.

    ``explicit`` is a project name a host or caller supplied; it is honoured
    verbatim (slugified) because the caller knows better than a path heuristic.
    """
    if explicit and explicit.strip():
        slug = slugify(explicit)
        if slug != "general":
            root = _normalize(cwd) if cwd else None
            return ProjectIdentity(slug, str(root) if root and str(root) else None, "explicit")
    if not cwd or not str(cwd).strip():
        return ProjectIdentity(UNSCOPED, None, UNSCOPED)
    start = _normalize(cwd)
    if not start.exists():
        # A vanished directory still gets a deterministic answer from its path.
        leaf = slugify(start.name)
        return ProjectIdentity(leaf if leaf != "general" else UNSCOPED, str(start), "cwd")
    if _is_home_or_system(start):
        # A shell opened in ~ or System32 is not "the repository that happens to
        # contain ~"; it is not a project at all.
        return ProjectIdentity(UNSCOPED, str(start), UNSCOPED)

    overrides = load_overrides(vault)
    if overrides:
        best = None
        for candidate in (start, *start.parents):
            slug = overrides.get(_key(candidate))
            if slug:
                best = (candidate, slug)
                break
        if best:
            return ProjectIdentity(best[1], str(best[0]), "override")

    git = _git_root(start)
    if git:
        worktree, identity_root = git
        pinned = _pinned(worktree) or _pinned(identity_root)
        if pinned:
            return ProjectIdentity(pinned, str(worktree), "pin")
        if _looks_unscoped(identity_root):
            return ProjectIdentity(UNSCOPED, str(worktree), UNSCOPED)
        return ProjectIdentity(slugify(identity_root.name), str(worktree), "git")

    marker = _marker_root(start)
    if marker:
        pinned = _pinned(marker)
        if pinned:
            return ProjectIdentity(pinned, str(marker), "pin")
        if _looks_unscoped(marker):
            return ProjectIdentity(UNSCOPED, str(marker), UNSCOPED)
        return ProjectIdentity(slugify(marker.name), str(marker), "marker")

    pinned = _pinned(start)
    if pinned:
        return ProjectIdentity(pinned, str(start), "pin")
    if _looks_unscoped(start):
        return ProjectIdentity(UNSCOPED, str(start), UNSCOPED)
    return ProjectIdentity(slugify(start.name), str(start), "cwd")


@lru_cache(maxsize=256)
def _cached(cwd_key: str, vault_key: str, explicit: str) -> ProjectIdentity:
    return resolve_project(cwd_key or None, vault=vault_key or None, explicit=explicit or None)


def resolve_project_cached(cwd: str | os.PathLike[str] | None, *, vault: Path | str | None = None,
                           explicit: str | None = None) -> ProjectIdentity:
    """Process-local cached variant for hot paths (hook receiver, worker loop)."""
    return _cached(str(cwd or ""), str(vault or ""), str(explicit or ""))


def clear_cache() -> None:
    _cached.cache_clear()
