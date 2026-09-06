"""Shared-file entity alias registry for kinds that route every subject into one
file (#35).

project/topic/decision/person each get their own file per subject, so their
identity lives in that file's own frontmatter (id/aliases) -- see vault.py's
FILE_PER_ENTITY_KINDS. preference and profile route every subject into one
shared file instead (/preferences.md, /profile.md), so there is no per-subject
file to carry that frontmatter. This registry is the equivalent for those two
kinds: a small, human-editable Markdown file recording which subjects are the
same entity, read at audit/conflict time to resolve one to the other.

It is deliberately a pure lookup. Nothing here rewrites an existing memory
entry's stored subject or merges records -- see MemoryManager.entity_alias_link
for the reviewed, reversible way to add an entry.
"""

from __future__ import annotations

import re
from pathlib import Path

from .utils import slugify

_SECTION_RE = re.compile(
    r"^## (?P<kind>[a-z]+): (?P<entity_id>[a-zA-Z0-9_-]+)\s*$\n(?P<body>.*?)(?=^## |\Z)",
    re.M | re.S,
)


def load_entity_aliases(path: Path) -> dict[str, dict[str, str]]:
    """Load the registry, if present.

    Returns, per kind, a mapping of every known alias slug (the entity's own id
    included) to its canonical entity id.
    """
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    resolved: dict[str, dict[str, str]] = {}
    for match in _SECTION_RE.finditer(content):
        kind = match.group("kind").strip().lower()
        entity_id = slugify(match.group("entity_id").strip())
        aliases = {entity_id}
        for line in match.group("body").splitlines():
            line = line.strip()
            if line.startswith("- "):
                alias = slugify(line[2:].strip())
                if alias:
                    aliases.add(alias)
        bucket = resolved.setdefault(kind, {})
        for alias in aliases:
            bucket[alias] = entity_id
    return resolved


def resolve_subject(registry: dict[str, dict[str, str]], kind: str, subject_slug: str) -> str:
    """Canonical entity id for subject_slug under kind, or subject_slug unchanged
    if it has no registered alias."""
    return registry.get(kind, {}).get(subject_slug, subject_slug)
