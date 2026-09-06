from __future__ import annotations

import re
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from .models import MemoryRecord
from .utils import atomic_write, file_lock, safe_join, slugify

# Files every connected AI tool trusts as instructions/index rather than ordinary
# memory content. Never writable via a caller-supplied target_path (issue #2).
RESERVED_FILENAMES = {"memory.md", "ai_instructions.md"}

# Kinds routed one file per subject, so identity (id/aliases) can live in that
# file's own frontmatter the way project's already did (#33), generalized here
# to topic/decision/person (#35). preference and profile route every subject
# into one shared file instead, so they use the separate entities.py registry.
FILE_PER_ENTITY_KINDS = {"project", "topic", "decision", "person"}

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
ENTRY_RE = re.compile(
    r"^- \[(?P<tag>[a-z]+)\] (?P<text>.*?) "
    r"<!-- mem:(?P<id>[a-zA-Z0-9_-]+) source:(?P<source>[a-zA-Z0-9_-]+)"
    r"(?: subject:(?P<subject>[a-zA-Z0-9_-]+))? "
    r"date:(?P<date>\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2})?) -->\s*$"
)
SESSION_RE = re.compile(r"^## (?P<slug>[a-zA-Z0-9_-]+)\s*\n(?P<body>.*?)(?=^## |\Z)", re.M | re.S)
SESSION_ID_RE = re.compile(r"<!-- session:(?P<id>[a-zA-Z0-9_-]+) -->")

def today() -> str:
    return date.today().isoformat()

def now_stamp() -> str:
    """Full local timestamp for new/edited entries. Older entries on disk keep their
    date-only stamp untouched — ENTRY_RE accepts both, so nothing needs migrating."""
    return datetime.now().isoformat(timespec="seconds")

def parse_frontmatter(content: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    raw = m.group(1).splitlines()
    data: dict = {}
    current_list = None
    for line in raw:
        if line.startswith("  - ") and current_list:
            data.setdefault(current_list, []).append(line[4:].strip())
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not value:
                data[key] = []
                current_list = key
            elif value.startswith("[") and value.endswith("]"):
                body = value[1:-1].strip()
                data[key] = [x.strip() for x in body.split(",") if x.strip()]
                current_list = None
            else:
                data[key] = value
                current_list = None
    return data, content[m.end():]

def dump_frontmatter(meta: dict) -> str:
    preferred = ["type", "aliases", "status", "created", "updated", "sources"]
    keys = preferred + [k for k in meta if k not in preferred]
    lines = ["---"]
    for key in keys:
        if key not in meta:
            continue
        value = meta[key]
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"

def ensure_metadata(content: str, *, kind: str, writer: str,
                    entity_id: str | None = None, alias: str | None = None) -> str:
    meta, body = parse_frontmatter(content)
    now = today()
    if not meta:
        meta = {
            "type": kind,
            "aliases": [],
            "status": "active",
            "created": now,
            "updated": now,
            "sources": [writer],
        }
        if kind in FILE_PER_ENTITY_KINDS:
            meta["id"] = entity_id or "general"
            meta["aliases"] = [alias] if alias else []
    else:
        meta["updated"] = now
        sources = meta.get("sources") or []
        if not isinstance(sources, list):
            sources = [str(sources)]
        if writer not in sources:
            sources.append(writer)
        meta["sources"] = sources
        meta.setdefault("created", now)
        meta.setdefault("status", "active")
        meta.setdefault("aliases", [])
        meta.setdefault("type", kind)
        if kind in FILE_PER_ENTITY_KINDS:
            meta.setdefault("id", entity_id or "general")
            aliases = meta.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = [str(aliases)]
            if alias and alias not in aliases and alias != meta["id"]:
                aliases.append(alias)
            meta["aliases"] = aliases
    return dump_frontmatter(meta) + body.lstrip("\n")

def parse_records(path: Path, vault_root: Path) -> list[MemoryRecord]:
    if not path.exists() or path.suffix.lower() != ".md":
        return []
    relative = "/" + path.relative_to(vault_root).as_posix()
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    kind = str(meta.get("type", "topic"))
    records = []
    if kind == "session":
        for block in SESSION_RE.finditer(body):
            session_id = SESSION_ID_RE.search(block.group("body"))
            if not session_id:
                continue
            lines = [line.strip() for line in block.group("body").splitlines()]
            digest = " ".join(line[2:].strip() for line in lines if line.startswith("- "))
            date_match = re.search(r"^\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2}(?:T[^\s]+)?)", block.group("body"), re.M)
            records.append(MemoryRecord(
                memory_id=session_id.group("id"), path=relative, text=digest or block.group("slug"),
                kind="session", tag="stated", subject=block.group("slug"),
                writer=path.stem, date=(date_match.group(1) if date_match else today()),
            ))
        return records
    for line in body.splitlines():
        m = ENTRY_RE.match(line)
        if m:
            records.append(
                MemoryRecord(
                    memory_id=m.group("id"),
                    path=relative,
                    text=m.group("text"),
                    kind=kind,
                    tag=m.group("tag"),
                    subject=m.group("subject") or path.stem,
                    writer=m.group("source"),
                    date=m.group("date"),
                )
            )
    return records

class Vault:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    def initialize(self, template_root: Path) -> list[str]:
        self.root.mkdir(parents=True, exist_ok=True)
        created = []
        for src in template_root.rglob("*"):
            rel = src.relative_to(template_root)
            dst = self.root / rel
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
            elif not dst.exists():
                if src.suffix.lower() == ".md":
                    content = src.read_text(encoding="utf-8").replace("YYYY-MM-DD", today())
                    dst.write_text(content, encoding="utf-8")
                else:
                    shutil.copy2(src, dst)
                created.append("/" + rel.as_posix())
        return created

    def resolve(self, relative: str) -> Path:
        return safe_join(self.root, relative)

    def read(self, relative: str) -> str:
        p = self.resolve(relative)
        if not p.exists():
            raise FileNotFoundError(relative)
        return p.read_text(encoding="utf-8")

    def all_memory_files(self) -> Iterable[Path]:
        for p in self.root.rglob("*.md"):
            if ".obsidian" in p.parts:
                continue
            yield p

    def canonical_path(self, kind: str, subject: str, *, project: str | None = None,
                       entity_id: str | None = None) -> str:
        subject_slug = slugify(subject)
        if kind == "profile":
            return "/profile.md"
        if kind == "preference":
            return "/preferences.md"
        if kind == "person":
            return f"/people/{self._entity_slug('people', subject_slug, entity_id)}.md"
        if kind == "project":
            return f"/projects/{self._entity_slug('projects', subject_slug, entity_id)}.md"
        if kind == "decision":
            return f"/decisions/{self._entity_slug('decisions', subject_slug, entity_id)}.md"
        if kind == "topic":
            return f"/topics/{self._entity_slug('topics', subject_slug, entity_id)}.md"
        if kind == "session":
            # Sessions are project-major: hook capture is per-working-directory, so a
            # writer-major layout would grow one unbounded file per agent spanning every
            # project. Sessions naming no project stay at the writer-major root path.
            model_slug = slugify(subject.split("-", 1)[0] or "other")
            if project:
                project_slug = self._entity_slug("projects", slugify(project), None)
                return f"/sessions/{project_slug}/{model_slug}.md"
            return f"/sessions/{model_slug}.md"
        return f"/topics/{subject_slug}.md"

    def _entity_slug(self, directory: str, subject_slug: str, entity_id: str | None) -> str:
        """Resolve by explicit identity or an existing exact alias, for any kind
        routed one file per subject (FILE_PER_ENTITY_KINDS): project originally
        (#33), generalized here to topic/decision/person (#35).

        Similar-looking names are reported by subject_audit and require an
        explicit link decision instead of a silent merge. A missing entity_id
        must not activate a prefix fallback: a caller that has not identified
        the entity must get a separate subject-based path (#37).
        """
        base = self.root / directory
        if not base.exists():
            return slugify(entity_id or subject_slug)
        wanted_id = slugify(entity_id) if entity_id else None
        for path in base.glob("*.md"):
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            current_id = slugify(str(meta.get("id", ""))) if meta.get("id") else path.stem
            aliases = meta.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = [str(aliases)]
            aliases = {slugify(str(value)) for value in aliases}
            if (wanted_id and current_id == wanted_id) or subject_slug == current_id or subject_slug in aliases:
                return path.stem
        return slugify(entity_id or subject_slug)

    def append_entry(self, relative: str, line: str, *, kind: str, writer: str,
                     entity_id: str | None = None, alias: str | None = None) -> None:
        p = self.resolve(relative)
        p.parent.mkdir(parents=True, exist_ok=True)
        # File creation happens *inside* the lock: two writers racing on a brand-new
        # file must not each write their own skeleton outside a critical section (#7).
        with file_lock(p):
            if p.exists():
                current = p.read_text(encoding="utf-8")
            else:
                title = p.stem.replace("-", " ").title()
                current = f"\n# {title}\n"
            current = ensure_metadata(
                current, kind=kind, writer=writer,
                entity_id=entity_id or (p.stem if kind in FILE_PER_ENTITY_KINDS else None), alias=alias
            ).rstrip() + "\n"
            if line not in current:
                if not current.endswith("\n\n"):
                    current += "\n"
                current += line.rstrip() + "\n"
            atomic_write(p, current)

    def append_session_block(self, relative: str, block: str, *, writer: str) -> None:
        p = self.resolve(relative)
        p.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(p):
            current = p.read_text(encoding="utf-8") if p.exists() else ""
            current = ensure_metadata(current, kind="session", writer=writer).rstrip()
            if current:
                current += "\n\n"
            atomic_write(p, current + block.rstrip() + "\n")

    def replace_entry_line(self, relative: str, memory_id: str, transform) -> bool:
        p = self.resolve(relative)
        if not p.exists():
            return False
        with file_lock(p):
            content = p.read_text(encoding="utf-8")
            lines = content.splitlines()
            changed = False
            for i, line in enumerate(lines):
                m = ENTRY_RE.match(line)
                if m and m.group("id") == memory_id:
                    lines[i] = transform(line)
                    changed = True
                    break
            if changed:
                atomic_write(p, "\n".join(lines) + "\n")
            return changed

    def delete_entry(self, relative: str, memory_id: str) -> bool:
        p = self.resolve(relative)
        if not p.exists():
            return False
        with file_lock(p):
            content = p.read_text(encoding="utf-8")
            lines = content.splitlines()
            out = []
            changed = False
            for line in lines:
                m = ENTRY_RE.match(line)
                if m and m.group("id") == memory_id:
                    changed = True
                    continue
                out.append(line)
            if changed:
                atomic_write(p, "\n".join(out) + "\n")
            return changed

    def delete_session_block(self, relative: str, memory_id: str) -> bool:
        """Remove the `## <slug>` block carrying `<!-- session:<id> -->`.

        Session records are heading blocks, not single lines, so `delete_entry`'s
        ENTRY_RE scan can never match them (#20). Frontmatter is left intact.
        """
        p = self.resolve(relative)
        if not p.exists():
            return False
        with file_lock(p):
            meta, body = parse_frontmatter(p.read_text(encoding="utf-8"))
            kept, changed = [], False
            for block in SESSION_RE.finditer(body):
                found = SESSION_ID_RE.search(block.group("body"))
                if found and found.group("id") == memory_id:
                    changed = True
                    continue
                kept.append(block.group(0).rstrip())
            if changed:
                rebuilt = dump_frontmatter(meta) if meta else ""
                if kept:
                    rebuilt += ("\n" if rebuilt else "") + "\n\n".join(kept) + "\n"
                atomic_write(p, rebuilt)
            return changed

    def orphan_session_blocks(self, relative: str) -> list[dict]:
        """Session heading blocks with no parseable `<!-- session:<id> -->` marker.

        `parse_records` skips these, so they are unindexed, unsearchable and
        undeletable while still sitting in the vault (#24).
        """
        p = self.resolve(relative)
        if not p.exists():
            return []
        _, body = parse_frontmatter(p.read_text(encoding="utf-8"))
        return [
            {"path": relative, "heading": block.group("slug")}
            for block in SESSION_RE.finditer(body)
            if not SESSION_ID_RE.search(block.group("body"))
        ]

    def ensure_index_entry(self, relative: str, kind: str, covers: str) -> None:
        idx = self.resolve("/MEMORY.md")
        link = relative.lstrip("/")
        if link.endswith(".md"):
            link = link[:-3]
        row_prefix = f"| [[{link}]] |"
        # Creation happens inside the same lock as the read-modify-write below —
        # a separate unlocked exists()/write_text() before the lock would race
        # the same way append_entry()'s did (#7).
        with file_lock(idx):
            if idx.exists():
                content = idx.read_text(encoding="utf-8")
            else:
                content = "# Memory Index\n\n| Path | Type | Updated | Covers |\n|---|---|---|---|\n"
            lines = content.splitlines()
            now = today()
            found = False
            for i, line in enumerate(lines):
                if line.startswith(row_prefix):
                    lines[i] = f"| [[{link}]] | {kind} | {now} | {covers} |"
                    found = True
                    break
            if not found:
                if lines and lines[-1].strip():
                    lines.append(f"| [[{link}]] | {kind} | {now} | {covers} |")
                else:
                    lines[-1] = f"| [[{link}]] | {kind} | {now} | {covers} |"
            atomic_write(idx, "\n".join(lines) + "\n")
