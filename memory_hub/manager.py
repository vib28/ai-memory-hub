from __future__ import annotations

import re
import uuid
from difflib import SequenceMatcher
from pathlib import Path

from .index import MemoryIndex
from .models import ALLOWED_KINDS, ALLOWED_TAGS, ALLOWED_WRITERS, SINGLETON_KINDS, MemoryCandidate, MemoryRecord
from .security import check_text
from .utils import normalize_text, text_hash
from .vault import Vault, ENTRY_RE, parse_records, ensure_metadata, now_stamp

AUTO_POLICY = """
Store automatically only when the information is durable, user-specific, future-useful,
high-confidence, non-sensitive, canonical, and non-duplicate.

Good automatic candidates:
- stable identity/role/stack/timezone
- durable response/workflow preferences
- important purchases that affect future recommendations
- long-running project objective/constraint/status
- explicit project or technology decisions
- recurring interests/preferences
- unresolved questions that materially affect ongoing work

Do not automatically store:
- secrets, credentials, tokens, IDs
- current prices or search results
- generated code/prose
- temporary bugs/errors
- today's errands or fleeting state
- uncertain plans
- casual one-off reactions
- sensitive inferred attributes

Prefer explicit user statements. Store AI inference only sparingly.
"""

class MemoryManager:
    def __init__(self, vault_root: str | Path):
        self.vault = Vault(Path(vault_root))
        self.vault.root.mkdir(parents=True, exist_ok=True)
        self.index = MemoryIndex(self.vault.root)

    def close(self):
        self.index.close()

    def initialize(self, template_root: Path) -> dict:
        created = self.vault.initialize(template_root)
        count = self.reindex()
        return {"created": created, "indexed": count}

    def _all_records(self) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for p in self.vault.all_memory_files():
            if p.name in {"MEMORY.md", "AI_INSTRUCTIONS.md"}:
                continue
            records.extend(parse_records(p, self.vault.root))
        return records

    def reindex(self) -> int:
        return self.index.rebuild(self._all_records())

    def _validate(self, candidate: MemoryCandidate) -> dict | None:
        candidate.text = " ".join(candidate.text.strip().split())
        candidate.kind = candidate.kind.strip().lower()
        candidate.tag = candidate.tag.strip().lower()
        candidate.writer = candidate.writer.strip().lower()
        candidate.subject = candidate.subject.strip() or "general"
        if candidate.kind not in ALLOWED_KINDS:
            return {"status": "rejected", "reason": f"invalid kind: {candidate.kind}"}
        if candidate.tag not in ALLOWED_TAGS - {"superseded"}:
            return {"status": "rejected", "reason": f"invalid tag for new memory: {candidate.tag}"}
        if candidate.writer not in ALLOWED_WRITERS:
            candidate.writer = "other"
        security = check_text(candidate.text)
        if not security.safe:
            return {"status": "rejected", "reason": security.reason}
        if candidate.tag == "inferred":
            return {"status": "rejected", "reason": "automatic inferred memories are disabled by default"}
        return None

    def _near_duplicate(self, text: str, threshold: float = 0.93):
        norm = normalize_text(text)
        for row in self.index.all_rows():
            if row["tag"] == "superseded":
                continue
            ratio = SequenceMatcher(None, norm, normalize_text(row["text"])).ratio()
            if ratio >= threshold:
                return row, ratio
        return None, 0.0

    def queue(self, candidate: MemoryCandidate) -> dict:
        problem = self._validate(candidate)
        if problem:
            return problem
        exact = self.index.exact_hash(text_hash(candidate.text))
        if exact:
            return {"status": "duplicate", "memory": exact}
        near, score = self._near_duplicate(candidate.text)
        if near:
            return {"status": "duplicate", "similarity": round(score, 3), "memory": near}
        dup = self.index.pending_duplicate(candidate.text, candidate.subject, candidate.kind)
        if dup:
            return {"status": "already_pending", "proposal": dup}
        row = self.index.enqueue(candidate.to_dict())
        return {"status": "queued", "proposal": row}

    def propose(self, candidate: MemoryCandidate) -> dict:
        problem = self._validate(candidate)
        if problem:
            return problem
        exact = self.index.exact_hash(text_hash(candidate.text))
        if exact:
            return {"status": "duplicate", "memory": exact}
        near, score = self._near_duplicate(candidate.text)
        if near:
            return {"status": "duplicate", "similarity": round(score, 3), "memory": near}

        relative = candidate.target_path or self.vault.canonical_path(candidate.kind, candidate.subject)
        relative = "/" + relative.replace("\\", "/").lstrip("/")
        if not relative.endswith(".md"):
            return {"status": "rejected", "reason": "target_path must be a Markdown file"}
        self.vault.resolve(relative)

        if candidate.supersedes_id:
            old = self.index.by_id(candidate.supersedes_id)
            if not old:
                return {"status": "rejected", "reason": f"supersedes_id not found: {candidate.supersedes_id}"}
            self._mark_superseded(old)

        memory_id = uuid.uuid4().hex[:12]
        stamp = now_stamp()
        line = f"- [{candidate.tag}] {candidate.text} <!-- mem:{memory_id} source:{candidate.writer} date:{stamp} -->"
        self.vault.append_entry(relative, line, kind=candidate.kind, writer=candidate.writer)
        self.vault.ensure_index_entry(relative, candidate.kind, self._covers(candidate))

        record = MemoryRecord(memory_id, relative, candidate.text, candidate.kind, candidate.tag,
                              candidate.subject, candidate.writer, stamp)
        self.index.upsert(record)
        return {"status": "stored", "memory": record.to_dict()}

    def approve(self, proposal_id: str) -> dict:
        row = self.index.pending_by_id(proposal_id)
        if not row or row["status"] != "pending":
            return {"status": "not_found", "proposal_id": proposal_id}
        candidate = MemoryCandidate(
            text=row["text"], kind=row["kind"], tag=row["tag"], subject=row["subject"],
            writer=row["writer"], target_path=row["target_path"], supersedes_id=row["supersedes_id"]
        )
        result = self.propose(candidate)
        self.index.set_pending_status(proposal_id, "approved" if result["status"] == "stored" else result["status"])
        return result

    def reject(self, proposal_id: str, note: str = "") -> dict:
        row = self.index.pending_by_id(proposal_id)
        if not row or row["status"] != "pending":
            return {"status": "not_found", "proposal_id": proposal_id}
        self.index.set_pending_status(proposal_id, "rejected", note)
        return {"status": "rejected", "proposal_id": proposal_id}

    def list_pending(self) -> list[dict]:
        return self.index.list_pending("pending")

    def _covers(self, candidate: MemoryCandidate) -> str:
        if candidate.kind == "profile":
            return "Stable identity, role, stack, timezone, and long-term context"
        if candidate.kind == "preference":
            return "Communication, workflow, research, and output preferences"
        return f"{candidate.kind.title()} memory for {candidate.subject}"

    def _mark_superseded(self, old: dict) -> bool:
        def transform(line: str) -> str:
            return re.sub(r"^- \[[a-z]+\]", "- [superseded]", line, count=1)
        changed = self.vault.replace_entry_line(old["path"], old["memory_id"], transform)
        if changed:
            old["tag"] = "superseded"
            self.index.upsert(MemoryRecord(old["memory_id"], old["path"], old["text"], old["kind"],
                                           "superseded", old["subject"], old["writer"], old["date"]))
        return changed

    def supersede(self, old_memory_id: str, candidate: MemoryCandidate) -> dict:
        candidate.supersedes_id = old_memory_id
        return self.propose(candidate)

    def edit(self, memory_id: str, new_text: str, writer: str = "user") -> dict:
        old = self.index.by_id(memory_id)
        if not old:
            return {"status": "not_found", "memory_id": memory_id}
        security = check_text(new_text)
        if not security.safe:
            return {"status": "rejected", "reason": security.reason}
        new_text = " ".join(new_text.strip().split())
        p = self.vault.resolve(old["path"])
        from .utils import file_lock, atomic_write
        with file_lock(p):
            content = p.read_text(encoding="utf-8")
            lines = content.splitlines()
            changed = False
            stamp = now_stamp()
            for i, line in enumerate(lines):
                m = ENTRY_RE.match(line)
                if m and m.group("id") == memory_id:
                    lines[i] = f"- [{old['tag']}] {new_text} <!-- mem:{memory_id} source:{writer} date:{stamp} -->"
                    changed = True
                    break
            if not changed:
                return {"status": "not_found_in_file", "memory_id": memory_id}
            body = "\n".join(lines) + "\n"
            body = ensure_metadata(body, kind=old["kind"], writer=writer)
            atomic_write(p, body)
        rec = MemoryRecord(memory_id, old["path"], new_text, old["kind"], old["tag"],
                           old["subject"], writer, stamp)
        self.index.upsert(rec)
        return {"status": "updated", "memory": rec.to_dict()}

    def forget(self, memory_id: str) -> dict:
        old = self.index.by_id(memory_id)
        if not old:
            return {"status": "not_found", "memory_id": memory_id}
        changed = self.vault.delete_entry(old["path"], memory_id)
        if changed:
            self.index.remove(memory_id)
            return {"status": "forgotten", "memory_id": memory_id, "path": old["path"]}
        return {"status": "not_found_in_file", "memory_id": memory_id, "path": old["path"]}

    def search(self, query: str, limit: int = 10) -> list[dict]:
        return self.index.search(query, limit)

    def read(self, path: str) -> str:
        return self.vault.read(path)

    def conflicts(self) -> list[dict]:
        groups = {}
        for row in self.index.all_rows():
            if row["tag"] == "superseded":
                continue
            key = (row["kind"], row["subject"])
            groups.setdefault(key, []).append(row)
        out = []
        for (kind, subject), rows in groups.items():
            if kind not in SINGLETON_KINDS:
                continue
            unique = {normalize_text(r["text"]) for r in rows}
            if len(rows) > 1 and len(unique) > 1:
                rows = sorted(rows, key=lambda r: (r["date"], r["memory_id"]))
                out.append({"kind": kind, "subject": subject, "memories": rows})
        return out

    def resolve_conflict(self, keep_id: str) -> dict:
        keep = self.index.by_id(keep_id)
        if not keep:
            return {"status": "not_found", "memory_id": keep_id}
        changed = []
        for row in self.index.all_rows():
            if row["memory_id"] == keep_id or row["tag"] == "superseded":
                continue
            if row["kind"] == keep["kind"] and row["subject"] == keep["subject"]:
                if self._mark_superseded(row):
                    changed.append(row["memory_id"])
        return {"status": "resolved", "kept": keep_id, "superseded": changed}

    def audit(self) -> dict:
        records = self._all_records()
        seen = {}
        duplicate_ids = []
        malformed_files = []
        for r in records:
            if r.memory_id in seen:
                duplicate_ids.append(r.memory_id)
            seen[r.memory_id] = r.path
        indexed_ids = {r["memory_id"] for r in self.index.all_rows()}
        file_ids = {r.memory_id for r in records}
        missing_from_index = sorted(file_ids - indexed_ids)
        stale_in_index = sorted(indexed_ids - file_ids)
        for p in self.vault.all_memory_files():
            if p.name in {"MEMORY.md", "AI_INSTRUCTIONS.md"}:
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
                if line.startswith("- [") and not ENTRY_RE.match(line):
                    malformed_files.append({"path": "/" + p.relative_to(self.vault.root).as_posix(),
                                            "line": i, "text": line[:200]})
        return {
            "records_in_files": len(records),
            "records_in_index": len(indexed_ids),
            "pending_review": len(self.list_pending()),
            "potential_conflicts": len(self.conflicts()),
            "duplicate_ids": sorted(set(duplicate_ids)),
            "missing_from_index": missing_from_index,
            "stale_in_index": stale_in_index,
            "malformed_memory_lines": malformed_files,
            "healthy": not (duplicate_ids or missing_from_index or stale_in_index or malformed_files),
        }
