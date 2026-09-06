from __future__ import annotations

import re
import uuid
import json
import shutil
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from .entities import load_entity_aliases, resolve_subject
from .index import MemoryIndex
from .embeddings import LocalEmbeddingProvider
from .models import ALLOWED_KINDS, ALLOWED_TAGS, ALLOWED_WRITERS, SINGLETON_KINDS, MemoryCandidate, MemoryRecord
from .patterns import load_patterns
from .security import check_text
from .utils import atomic_write, file_lock, normalize_text, slugify, text_hash
from .vault import (Vault, ENTRY_RE, FILE_PER_ENTITY_KINDS, RESERVED_FILENAMES, parse_frontmatter,
                    parse_records, dump_frontmatter, ensure_metadata, now_stamp)

# Kinds that route every subject into one shared file, so there is no
# per-subject file to carry id/aliases frontmatter -- identity for these is
# resolved through the entity-aliases.md registry instead (#35).
SHARED_FILE_KINDS = {"preference", "profile"}

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
        self.index = MemoryIndex(self.vault.root, LocalEmbeddingProvider.from_environment())

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
        candidate.subject = slugify(candidate.subject.strip() or "general")
        if candidate.entity_id:
            candidate.entity_id = slugify(candidate.entity_id.strip())
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

    # Ratio at/above this is treated as the same fact restated verbatim: a genuine
    # duplicate, safe to hard-block. Ratio in the DUPLICATE_UPDATE_BAND below this
    # is close enough to be the same subject but differs by a token (a version
    # bump, a spelling fix) — that's an *update* the user likely wants applied,
    # not a duplicate to silently drop, so it is routed to review instead (#3).
    TRUE_DUPLICATE_THRESHOLD = 0.985
    DUPLICATE_UPDATE_BAND = 0.85

    def _best_match(self, text: str, kind: str):
        """Find the closest same-kind row using vectors when safely available.

        The lexical scan remains the conservative fallback for missing, incomplete, or
        failed embeddings. Threshold classification stays in this manager (#27).
        """
        norm = normalize_text(text)
        best_row, best_ratio = None, 0.0
        rows = self.index.vector_candidates(text, kind)
        if rows is None:
            rows = self.index.all_rows()
        for row in rows:
            if row["tag"] == "superseded" or row["kind"] != kind:
                continue
            ratio = SequenceMatcher(None, norm, normalize_text(row["text"])).ratio()
            if ratio > best_ratio:
                best_row, best_ratio = row, ratio
        return best_row, best_ratio

    def _duplicate_or_update(self, candidate: MemoryCandidate):
        """Returns (status_dict, near_update_row_or_None). status_dict is set only
        for a genuine, hard-blocking duplicate; near_update_row is set when a close
        but not identical match exists so the caller can route it for review."""
        if candidate.supersedes_id:
            return None, None
        exact = self.index.exact_hash(text_hash(candidate.text), candidate.kind)
        if exact:
            return {"status": "duplicate", "memory": exact}, None
        match, score = self._best_match(candidate.text, candidate.kind)
        if match and score >= self.TRUE_DUPLICATE_THRESHOLD:
            return {"status": "duplicate", "similarity": round(score, 3), "memory": match}, None
        if match and score >= self.DUPLICATE_UPDATE_BAND:
            return None, (match, score)
        return None, None

    def queue(self, candidate: MemoryCandidate) -> dict:
        problem = self._validate(candidate)
        if problem:
            return problem
        blocked, update = self._duplicate_or_update(candidate)
        if blocked:
            return blocked
        if update:
            match, score = update
            candidate.supersedes_id = match["memory_id"]
            row = self.index.enqueue(candidate.to_dict())
            return {"status": "queued_as_update", "similarity": round(score, 3),
                    "supersedes": match["memory_id"], "proposal": row}
        dup = self.index.pending_duplicate(candidate.text, candidate.subject, candidate.kind)
        if dup:
            return {"status": "already_pending", "proposal": dup}
        row = self.index.enqueue(candidate.to_dict())
        return {"status": "queued", "proposal": row}

    def _session_payload(self, data: dict) -> dict:
        required = ("model", "title", "investigated", "learned", "completed", "next_steps")
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError("missing session fields: " + ", ".join(missing))
        clean = {key: data[key] for key in required}
        clean["project"] = data.get("project")
        clean["date"] = data.get("date") or now_stamp()
        for key in required:
            if key in {"model", "title"}:
                if not str(clean[key]).strip():
                    raise ValueError(f"session {key} must not be empty")
            else:
                value = clean[key]
                if isinstance(value, str):
                    value = [value]
                clean[key] = [" ".join(str(item).strip().split()) for item in value if str(item).strip()]
        clean["model"] = str(clean["model"]).strip().lower()
        clean["title"] = str(clean["title"]).strip()
        clean["project"] = str(clean["project"]).strip() if clean["project"] else None
        return clean

    def _session_block(self, data: dict, memory_id: str) -> tuple[str, str]:
        slug = slugify(f"{data['model']}-{data['title']}-{data['date'].replace(':', '').replace('T', '-')}")
        tags = f"#{slugify(data['model'])} #{str(data['date'])[:10]}"
        project = f"[[{slugify(data['project'])}]]" if data.get("project") else "None"
        lines = [f"## {slug}", f"**Model:** {data['model']}", f"**Session title:** {data['title']}",
                 f"**Date:** {data['date']}", f"**Project:** {project}", f"**Tags:** {tags}", ""]
        for heading, key in (("Investigated", "investigated"), ("Learned", "learned"),
                             ("Completed", "completed"), ("Next Steps", "next_steps")):
            lines.append(f"### {heading}")
            lines.extend(f"- {item}" for item in data[key])
            lines.append("")
        lines.append(f"<!-- session:{memory_id} -->")
        return slug, "\n".join(lines).rstrip()

    def _duplicate_session(self, model: str, title: str, text: str) -> dict | None:
        """An already-stored session by the same writer, under the same title, with a
        byte-identical body.

        The date is deliberately excluded: `session_write` stamps `now` whenever the
        client omits one, so a retry after a transport timeout carries a *different*
        date than the call it repeats. Matching on it would miss the one case this
        exists to catch. Distinct sessions that merely resemble each other are
        untouched — this is a log kind, not a singleton kind.
        """
        target = text_hash(text)
        prefix = slugify(f"{model}-{title}") + "-"
        for row in self.index.all_rows():
            if row["kind"] != "session" or row["tag"] == "superseded":
                continue
            if (row["writer"] == model and row["normalized_hash"] == target
                    and str(row["subject"]).startswith(prefix)):
                return row
        return None

    def propose_session(self, data: dict, *, write_mode: str = "auto") -> dict:
        try:
            data = self._session_payload(data)
        except (TypeError, ValueError) as exc:
            return {"status": "rejected", "reason": str(exc)}
        if data["model"] not in ALLOWED_WRITERS:
            data["model"] = "other"
        section_text = " ".join(
            item
            for key in ("investigated", "learned", "completed", "next_steps")
            for item in data[key]
        )
        if not section_text:
            return {"status": "rejected", "reason": "empty memory"}
        security = check_text(section_text)
        if not security.safe:
            return {"status": "rejected", "reason": security.reason}
        subject = slugify(f"{data['model']}-{data['title']}-{data['date']}")
        candidate = MemoryCandidate(" ".join(sum((data[k] for k in ("investigated", "learned", "completed", "next_steps")), [])),
                                    "session", "stated", subject, data["model"])
        # Sessions are a log kind, so near-matches must still both be stored — but an
        # identical payload is a retry (client timeout, or a crash sweep re-firing a
        # completed session), not a second session. Key on identity, not similarity (#25).
        duplicate = self._duplicate_session(data["model"], data["title"], candidate.text)
        if duplicate:
            return {"status": "duplicate", "memory": duplicate}
        if write_mode == "review":
            row = self.index.enqueue(candidate.to_dict(), payload={"type": "session", "data": data})
            return {"status": "queued", "proposal": row, "label": "session summary"}
        memory_id = uuid.uuid4().hex[:12]
        slug, block = self._session_block(data, memory_id)
        relative = self.vault.canonical_path("session", data["model"], project=data.get("project"))
        self.vault.append_session_block(relative, block, writer=data["model"])
        covers = f"Session summaries for {data['model']}"
        if data.get("project"):
            covers += f" on {data['project']}"
        self.vault.ensure_index_entry(relative, "session", covers)
        record = MemoryRecord(memory_id, relative, candidate.text, "session", "stated", slug, data["model"], data["date"])
        self.index.upsert(record)
        linked = None
        if data.get("project"):
            linked = self.propose(MemoryCandidate(
                text=f"Session summary [[{slug}]]: {candidate.text}", kind="project", tag="stated",
                subject=data["project"], writer=data["model"]))
        result = {"status": "stored", "memory": record.to_dict(), "project": linked}
        # The session itself is written, but a cross-link that came back
        # `possible_update` wrote nothing. Reporting a bare "stored" here loses it
        # silently, which is exactly the trap that makes sessions drift out of their
        # project files (#22). Surface it, and hand back what supersede() needs.
        if linked and linked.get("status") == "possible_update":
            result["status"] = "stored_without_project_link"
            result["project_link_supersedes"] = linked["memory"]["memory_id"]
            result["hint"] = ("Session stored; its project cross-link matched an existing "
                              "entry and was not written. Call supersede() with "
                              "project_link_supersedes to apply it.")
        return result

    def patterns(self) -> dict:
        """Return validated user-configured patterns for supported callers."""
        return load_patterns(self.vault.resolve("/patterns.md"))

    def _patterns(self) -> dict:
        """Compatibility wrapper for internal callers."""
        return self.patterns()

    def propose_pattern_match(self, pattern_id: str, project_fact_text: str, preference_rule_text: str,
                              subject: str, *, write_mode: str = "auto", writer: str = "other") -> dict:
        try:
            patterns = self.patterns()
        except ValueError as exc:
            return {"status": "rejected", "reason": str(exc)}
        if pattern_id not in patterns:
            return {"status": "rejected", "reason": f"unknown pattern: {pattern_id}"}
        subject = slugify(subject)
        link = f"[[{subject}]]"
        project_text = f"{project_fact_text.strip()} {link}"
        preference_text = f"{preference_rule_text.strip()} {link}"
        existing, score = self._best_match(preference_text, "preference")
        confirmed = bool(existing and score >= self.DUPLICATE_UPDATE_BAND)
        label = "confirmed pattern" if confirmed else "first occurrence"
        payload = {"type": "pattern", "pattern_id": pattern_id, "project_fact_text": project_fact_text,
                   "preference_rule_text": preference_rule_text, "subject": subject, "writer": writer, "label": label,
                   "preference_supersedes": existing["memory_id"] if confirmed else None}
        if write_mode == "review":
            candidate = MemoryCandidate(project_text, "project", "stated", subject, writer)
            row = self.index.enqueue(candidate.to_dict(), payload=payload)
            return {"status": "queued", "proposal": row, "label": label}
        # Both halves are validated before either is written. The two writes are what
        # make a pattern a pattern: committing the project fact and then failing on the
        # preference rule leaves an orphaned fact whose linked rule never existed (#23).
        project_candidate = MemoryCandidate(project_text, "project", "stated", subject, writer)
        preference_candidate = MemoryCandidate(
            preference_text, "preference", "preference", subject, writer,
            supersedes_id=existing["memory_id"] if confirmed else None)
        for candidate in (project_candidate, preference_candidate):
            problem = self._validate(candidate)
            if problem:
                return {**problem, "label": label, "half": candidate.kind}

        project = self.propose(project_candidate)
        if project.get("status") not in {"stored", "duplicate"}:
            return {**project, "label": label, "half": "project"}
        preference = self.propose(preference_candidate)
        if preference.get("status") not in {"stored", "duplicate"}:
            # The project half is already committed; say so rather than reporting a
            # bare status the caller cannot act on.
            return {**preference, "label": label, "half": "preference",
                    "project": project,
                    "hint": "The project fact was written but its linked preference rule "
                            "was not. Resolve the preference half to complete the pattern."}
        return {"status": "stored", "label": label, "project": project, "preference": preference}

    def propose(self, candidate: MemoryCandidate) -> dict:
        problem = self._validate(candidate)
        if problem:
            return problem
        blocked, update = self._duplicate_or_update(candidate)
        if blocked:
            return blocked
        if update:
            match, score = update
            return {"status": "possible_update", "similarity": round(score, 3), "memory": match,
                     "hint": "Nearly identical to an existing memory. Call supersede() with this "
                             "memory_id (or set supersedes_id) if this is meant to update it."}

        relative = candidate.target_path or self.vault.canonical_path(
            candidate.kind, candidate.subject, entity_id=candidate.entity_id
        )
        relative = "/" + relative.replace("\\", "/").lstrip("/")
        if not relative.endswith(".md"):
            return {"status": "rejected", "reason": "target_path must be a Markdown file"}
        if Path(relative).name.lower() in RESERVED_FILENAMES:
            return {"status": "rejected", "reason": f"target_path may not write to reserved file: {relative}"}
        self.vault.resolve(relative)

        if candidate.supersedes_id:
            old = self.index.by_id(candidate.supersedes_id)
            if not old:
                return {"status": "rejected", "reason": f"supersedes_id not found: {candidate.supersedes_id}"}
            self._mark_superseded(old)

        memory_id = uuid.uuid4().hex[:12]
        stamp = now_stamp()
        line = (
            f"- [{candidate.tag}] {candidate.text} "
            f"<!-- mem:{memory_id} source:{candidate.writer} subject:{candidate.subject} date:{stamp} -->"
        )
        self.vault.append_entry(
            relative, line, kind=candidate.kind, writer=candidate.writer,
            entity_id=candidate.entity_id, alias=candidate.subject,
        )
        self.vault.ensure_index_entry(relative, candidate.kind, self._covers(candidate))

        record = MemoryRecord(memory_id, relative, candidate.text, candidate.kind, candidate.tag,
                              candidate.subject, candidate.writer, stamp)
        self.index.upsert(record)
        return {"status": "stored", "memory": record.to_dict()}

    def approve(self, proposal_id: str) -> dict:
        row = self.index.pending_by_id(proposal_id)
        if not row or row["status"] != "pending":
            return {"status": "not_found", "proposal_id": proposal_id}
        if row.get("payload"):
            payload = json.loads(row["payload"])
            if payload.get("type") == "session":
                result = self.propose_session(payload["data"], write_mode="auto")
                # The session is written in both cases; only its cross-link differs (#22).
                stored = result["status"] in {"stored", "stored_without_project_link"}
                self.index.set_pending_status(proposal_id, "approved" if stored else result["status"])
                return result
            if payload.get("type") == "pattern":
                result = self.propose_pattern_match(payload["pattern_id"], payload["project_fact_text"],
                    payload["preference_rule_text"], payload["subject"], write_mode="auto", writer=payload["writer"])
                self.index.set_pending_status(proposal_id, "approved" if result["status"] == "stored" else result["status"])
                return result
        candidate = MemoryCandidate(
            text=row["text"], kind=row["kind"], tag=row["tag"], subject=row["subject"],
            writer=row["writer"], target_path=row["target_path"], supersedes_id=row["supersedes_id"],
            entity_id=row.get("entity_id"),
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

    def list_proposal_history(self) -> list[dict]:
        return self.index.list_pending(None)

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
            subject = slugify(old["subject"])
            for i, line in enumerate(lines):
                m = ENTRY_RE.match(line)
                if m and m.group("id") == memory_id:
                    lines[i] = (
                        f"- [{old['tag']}] {new_text} "
                        f"<!-- mem:{memory_id} source:{writer} subject:{subject} date:{stamp} -->"
                    )
                    changed = True
                    break
            if not changed:
                return {"status": "not_found_in_file", "memory_id": memory_id}
            body = "\n".join(lines) + "\n"
            body = ensure_metadata(body, kind=old["kind"], writer=writer)
            atomic_write(p, body)
        rec = MemoryRecord(memory_id, old["path"], new_text, old["kind"], old["tag"],
                           subject, writer, stamp)
        self.index.upsert(rec)
        return {"status": "updated", "memory": rec.to_dict()}

    def forget(self, memory_id: str) -> dict:
        old = self.index.by_id(memory_id)
        if not old:
            return {"status": "not_found", "memory_id": memory_id}
        # Sessions are heading blocks, not entry lines, and need their own deletion
        # path — dispatching on kind is what makes them removable at all (#20).
        if old["kind"] == "session":
            changed = self.vault.delete_session_block(old["path"], memory_id)
        else:
            changed = self.vault.delete_entry(old["path"], memory_id)
        if changed:
            self.index.remove(memory_id)
            return {"status": "forgotten", "memory_id": memory_id, "path": old["path"]}
        return {"status": "not_found_in_file", "memory_id": memory_id, "path": old["path"]}

    def search(self, query: str, limit: int = 10) -> list[dict]:
        return self.index.search(query, limit)

    def context_prime(self, *, project: str | None = None, query: str | None = None,
                      limit: int = 5, max_chars: int = 4000) -> dict:
        """Return a bounded session-start context packet from durable memory."""
        project = (project or "").strip()
        query = (query or "").strip()
        search_query = " ".join(part for part in (project, query) if part).strip() or "general"
        rows = self.search(search_query, max(1, min(int(limit), 20)))
        selected = []
        used = 0
        for row in rows:
            item = {
                "memory_id": row["memory_id"],
                "path": row["path"],
                "kind": row["kind"],
                "subject": row["subject"],
                "text": row["text"],
            }
            cost = len(json.dumps(item, ensure_ascii=False))
            if selected and used + cost > max(500, min(int(max_chars), 12000)):
                break
            selected.append(item)
            used += cost
        return {
            "status": "ok",
            "project": project or None,
            "query": query or None,
            "memories": selected,
            "characters": used,
            "truncated": len(selected) < len(rows),
        }

    def read(self, path: str) -> str:
        return self.vault.read(path)

    def entity_registry(self) -> dict[str, dict[str, str]]:
        return load_entity_aliases(self.vault.root / "entity-aliases.md")

    def conflicts(self) -> list[dict]:
        registry = self.entity_registry()
        groups = {}
        for row in self.index.all_rows():
            if row["tag"] == "superseded":
                continue
            subject = row["subject"]
            if row["kind"] in SHARED_FILE_KINDS:
                # An explicitly linked alias (#35) must be compared as one entity,
                # not left invisible because the two entries used different
                # subject strings -- see entity_alias_link().
                subject = resolve_subject(registry, row["kind"], slugify(subject))
            key = (row["kind"], subject)
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
        registry = self.entity_registry() if keep["kind"] in SHARED_FILE_KINDS else {}
        keep_subject = resolve_subject(registry, keep["kind"], slugify(keep["subject"])) \
            if registry else keep["subject"]
        changed = []
        for row in self.index.all_rows():
            if row["memory_id"] == keep_id or row["tag"] == "superseded":
                continue
            if row["kind"] != keep["kind"]:
                continue
            # Same widening conflicts() applies: an explicitly linked alias must
            # resolve to the same entity here too, or resolve_conflict() would
            # silently miss the rows conflicts() just showed the reviewer (#35).
            row_subject = resolve_subject(registry, row["kind"], slugify(row["subject"])) \
                if registry else row["subject"]
            if row_subject == keep_subject:
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
        orphan_sessions = []
        for p in self.vault.all_memory_files():
            if p.name in {"MEMORY.md", "AI_INSTRUCTIONS.md"}:
                continue
            relative = "/" + p.relative_to(self.vault.root).as_posix()
            content = p.read_text(encoding="utf-8")
            for i, line in enumerate(content.splitlines(), start=1):
                if line.startswith("- [") and not ENTRY_RE.match(line):
                    malformed_files.append({"path": relative, "line": i, "text": line[:200]})
            # A session block whose id marker was lost (a hand edit in Obsidian will do
            # it) is invisible to parse_records, so neither side of the file/index
            # reconciliation above can see it. Check the files directly (#24).
            meta, _ = parse_frontmatter(content)
            if str(meta.get("type", "")) == "session":
                orphan_sessions.extend(self.vault.orphan_session_blocks(relative))
        return {
            "records_in_files": len(records),
            "records_in_index": len(indexed_ids),
            "pending_review": len(self.list_pending()),
            "potential_conflicts": len(self.conflicts()),
            "duplicate_ids": sorted(set(duplicate_ids)),
            "missing_from_index": missing_from_index,
            "stale_in_index": stale_in_index,
            "malformed_memory_lines": malformed_files,
            "orphan_session_blocks": orphan_sessions,
            "healthy": not (duplicate_ids or missing_from_index or stale_in_index
                            or malformed_files or orphan_sessions),
        }

    def project_audit(self) -> dict:
        """Report project identity collisions and duplicate candidates without mutation."""
        projects_dir = self.vault.root / "projects"
        projects = []
        identity_paths: dict[str, list[str]] = {}
        if projects_dir.exists():
            paths = sorted(projects_dir.glob("*.md"))
        else:
            paths = []
        for path in paths:
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            identity = slugify(str(meta.get("id") or path.stem))
            aliases = meta.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = [str(aliases)]
            aliases = sorted({slugify(str(value)) for value in aliases if str(value).strip()})
            relative = "/" + path.relative_to(self.vault.root).as_posix()
            projects.append({"path": relative, "entity_id": identity, "aliases": aliases})
            for name in [identity, *aliases]:
                identity_paths.setdefault(name, []).append(relative)
        alias_collisions = [
            {"alias": alias, "paths": sorted(set(paths))}
            for alias, paths in sorted(identity_paths.items()) if len(set(paths)) > 1
        ]
        records = [r for r in self._all_records() if r.kind == "project" and r.tag != "superseded"]
        by_hash: dict[str, list[dict]] = {}
        for record in records:
            by_hash.setdefault(text_hash(record.text), []).append(record.to_dict())
        exact_duplicates = [rows for rows in by_hash.values() if len(rows) > 1]
        stems = [Path(item["path"]).stem for item in projects]
        possible_splits = []
        for left in sorted(stems):
            for right in sorted(stems):
                if left < right and (right.startswith(left + "-") or left.startswith(right + "-")):
                    possible_splits.append({"paths": [f"/projects/{left}.md", f"/projects/{right}.md"]})
        return {
            "projects": projects,
            "alias_collisions": alias_collisions,
            "exact_duplicate_groups": exact_duplicates,
            "possible_name_splits": possible_splits,
            "healthy": not (alias_collisions or exact_duplicates or possible_splits),
        }

    # Kinds routed one file per subject (vault.canonical_path), so a filename-level
    # split check is meaningful for them the same way it already is for "project".
    # "session" is deliberately excluded: its files are partitioned by project
    # directory and its subjects are per-instance (writer-title-date), so comparing
    # bare stems or subject strings there would flag unrelated files/records that
    # merely share a writer or wording, not sprawl. "preference" and "profile" share
    # one file across all their subjects, so there is no per-subject file to split --
    # they still get subject-variant comparison, just not the file-split check.
    _SUBJECT_SPRAWL_DIRS = {"project": "projects", "topic": "topics",
                            "decision": "decisions", "person": "people"}

    def subject_audit(self, kinds: list[str] | None = None) -> dict:
        """Read-only report of exact duplicates and subject-variant candidates across
        memory kinds (#34).

        Generalizes project_audit()'s exact-hash and possible-split detection to every
        kind, reusing the same text_hash/normalize_text identity the write path already
        uses (#3's TRUE_DUPLICATE_THRESHOLD path) so a finding here is exactly what
        propose() would reject as a duplicate had it been offered as a fresh write.

        This command only reads. It never edits Markdown, changes a tag, touches the
        index, or writes to the review queue -- see project_link() for the reviewed,
        reversible merge path once a finding here has been looked at.
        """
        target_kinds = sorted(set(kinds) & ALLOWED_KINDS) if kinds else sorted(ALLOWED_KINDS)
        records = [r for r in self._all_records() if r.kind in target_kinds and r.tag != "superseded"]
        registry = self.entity_registry()

        by_kind_hash: dict[tuple[str, str], list[dict]] = {}
        for record in records:
            by_kind_hash.setdefault((record.kind, text_hash(record.text)), []).append(record.to_dict())
        exact_duplicate_groups = [rows for rows in by_kind_hash.values() if len(rows) > 1]

        by_kind_subject: dict[str, set[str]] = {}
        for record in records:
            if record.kind == "session":
                continue
            by_kind_subject.setdefault(record.kind, set()).add(record.subject)
        subject_variant_candidates = []
        linked_entities = []
        for kind, subjects in sorted(by_kind_subject.items()):
            ordered = sorted(subjects)
            for left in ordered:
                for right in ordered:
                    if not (left < right and (right.startswith(left + "-") or left.startswith(right + "-"))):
                        continue
                    if kind in SHARED_FILE_KINDS and registry.get(kind, {}).get(left) is not None \
                            and resolve_subject(registry, kind, left) == resolve_subject(registry, kind, right):
                        # A reviewer already confirmed this pair via entity_alias_link():
                        # report it as resolved, not as an open candidate.
                        linked_entities.append({
                            "kind": kind, "subjects": [left, right],
                            "entity_id": resolve_subject(registry, kind, left),
                        })
                    else:
                        subject_variant_candidates.append({"kind": kind, "subjects": [left, right]})

        possible_file_splits = []
        alias_collisions = []
        for kind in target_kinds:
            directory = self._SUBJECT_SPRAWL_DIRS.get(kind)
            if not directory:
                continue
            base = self.vault.root / directory
            if not base.exists():
                continue
            stems = sorted(p.stem for p in base.glob("*.md"))
            for left in stems:
                for right in stems:
                    if left < right and (right.startswith(left + "-") or left.startswith(right + "-")):
                        possible_file_splits.append({
                            "kind": kind,
                            "paths": [f"/{directory}/{left}.md", f"/{directory}/{right}.md"],
                        })
            # Two files under the same kind whose id/aliases overlap is an
            # inconsistency worth surfacing on its own (e.g. a hand edit that
            # duplicated an id) -- generalizes project_audit()'s alias_collisions
            # to every FILE_PER_ENTITY_KINDS kind, not just project (#35).
            identity_paths: dict[str, list[str]] = {}
            for path in base.glob("*.md"):
                meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
                identity = slugify(str(meta.get("id") or path.stem))
                aliases = meta.get("aliases") or []
                if not isinstance(aliases, list):
                    aliases = [str(aliases)]
                aliases = {slugify(str(value)) for value in aliases if str(value).strip()}
                relative = f"/{directory}/{path.stem}.md"
                for name in [identity, *aliases]:
                    identity_paths.setdefault(name, []).append(relative)
            for alias, paths in sorted(identity_paths.items()):
                if len(set(paths)) > 1:
                    alias_collisions.append({"kind": kind, "alias": alias, "paths": sorted(set(paths))})

        return {
            "kinds": target_kinds,
            "exact_duplicate_groups": exact_duplicate_groups,
            "subject_variant_candidates": subject_variant_candidates,
            "possible_file_splits": possible_file_splits,
            "alias_collisions": alias_collisions,
            "linked_entities": linked_entities,
            "healthy": not (exact_duplicate_groups or subject_variant_candidates
                            or possible_file_splits or alias_collisions),
        }

    def project_link(self, source_path: str, target_path: str, *, apply: bool = False) -> dict:
        """Preview or apply an explicit, reversible file-per-entity merge.

        Originally project-only (#33); generalized to every FILE_PER_ENTITY_KINDS
        kind (topic/decision/person too) since their identity metadata is now the
        same id/aliases frontmatter shape (#35). The name stays project_link for
        backward compatibility with the existing public MCP tool and CLI command.
        """
        source = self.vault.resolve(source_path)
        target = self.vault.resolve(target_path)
        if source == target:
            return {"status": "rejected", "reason": "source and target must differ"}
        if source.suffix.lower() != ".md" or target.suffix.lower() != ".md":
            return {"status": "rejected", "reason": "paths must be Markdown files"}
        if not source.exists() or not target.exists():
            return {"status": "rejected", "reason": "both files must exist"}
        source_meta, source_body = parse_frontmatter(source.read_text(encoding="utf-8"))
        target_meta, target_body = parse_frontmatter(target.read_text(encoding="utf-8"))
        source_kind, target_kind = source_meta.get("type"), target_meta.get("type")
        if source_kind not in FILE_PER_ENTITY_KINDS or target_kind not in FILE_PER_ENTITY_KINDS:
            return {"status": "rejected",
                    "reason": "both files must have a type in " + ", ".join(sorted(FILE_PER_ENTITY_KINDS))}
        if source_kind != target_kind:
            return {"status": "rejected",
                    "reason": f"source and target must be the same kind (got {source_kind} and {target_kind})"}
        source_records = parse_records(source, self.vault.root)
        target_records = parse_records(target, self.vault.root)
        target_ids = {record.memory_id for record in target_records}
        movable = [record for record in source_records if record.memory_id not in target_ids]
        source_identity = slugify(str(source_meta.get("id") or source.stem))
        aliases = target_meta.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = [str(aliases)]
        aliases = list(dict.fromkeys([str(value) for value in aliases] + [source.stem, source_identity]))
        result = {
            "status": "preview" if not apply else "linked",
            "source": "/" + source.relative_to(self.vault.root).as_posix(),
            "target": "/" + target.relative_to(self.vault.root).as_posix(),
            "source_entity_id": source_identity,
            "target_entity_id": str(target_meta.get("id") or target.stem),
            "records_found": len(source_records),
            "records_to_move": len(movable),
            "memory_ids": [record.memory_id for record in movable],
            "aliases_added": aliases,
        }
        if not apply:
            return result
        lock_paths = sorted((source, target), key=lambda path: str(path).lower())
        with file_lock(lock_paths[0]):
            with file_lock(lock_paths[1]):
                # Re-read after locking so an approval cannot overwrite a concurrent edit.
                source_text = source.read_text(encoding="utf-8")
                target_text = target.read_text(encoding="utf-8")
                source_meta, source_body = parse_frontmatter(source_text)
                target_meta, target_body = parse_frontmatter(target_text)
                source_records = parse_records(source, self.vault.root)
                target_records = parse_records(target, self.vault.root)
                target_ids = {record.memory_id for record in target_records}
                lines = [line for line in source_body.splitlines() if ENTRY_RE.match(line)
                         and ENTRY_RE.match(line).group("id") not in target_ids]
                target_meta["aliases"] = aliases
                target_meta["updated"] = datetime.now().date().isoformat()
                merged_body = target_body.rstrip()
                if lines:
                    if merged_body:
                        merged_body += "\n\n"
                    merged_body += "\n".join(lines)
                atomic_write(target, dump_frontmatter(target_meta) + merged_body.rstrip() + "\n")
                backup = source.with_name(source.name + ".merged-" + datetime.now().strftime("%Y%m%d%H%M%S%f"))
                shutil.move(str(source), str(backup))
        result["backup"] = "/" + backup.relative_to(self.vault.root).as_posix()
        result["records_to_move"] = len(lines)
        self.reindex()
        return result

    def entity_alias_link(self, kind: str, source_subject: str, target_subject: str,
                          *, apply: bool = False) -> dict:
        """Preview or apply linking two subjects of a shared-file kind (preference,
        profile) as the same entity (#35).

        Unlike project_link, nothing is merged, moved, or rewritten: every existing
        memory entry keeps its own stored subject and stays exactly where it is and
        fully readable. This only adds or updates one small section in the
        entity-aliases.md registry (see entities.py), so it is trivially reversible
        by hand-editing that file or, if vault history is enabled, through normal
        Git revert -- there is no backup file to manage because nothing destructive
        happens.
        """
        if kind not in SHARED_FILE_KINDS:
            return {"status": "rejected",
                    "reason": f"entity_alias_link is only for {sorted(SHARED_FILE_KINDS)}; "
                              f"use project_link for a file-per-subject kind"}
        source_slug = slugify(source_subject)
        target_slug = slugify(target_subject)
        if source_slug == target_slug:
            return {"status": "rejected", "reason": "source and target must differ"}
        registry_path = self.vault.root / "entity-aliases.md"
        registry = load_entity_aliases(registry_path)
        bucket = registry.get(kind, {})
        # If either side is already linked, keep its existing canonical id so two
        # separate link calls can't fork one entity into two registry entries.
        canonical = bucket.get(target_slug) or bucket.get(source_slug) or target_slug
        combined_aliases = sorted(
            {alias for alias, cid in bucket.items() if cid == canonical} | {source_slug, target_slug}
        )
        result = {
            "status": "preview" if not apply else "linked",
            "kind": kind,
            "entity_id": canonical,
            "aliases": combined_aliases,
        }
        if not apply:
            return result
        with file_lock(registry_path):
            # Re-read after locking so a concurrent link cannot be silently dropped.
            content = registry_path.read_text(encoding="utf-8") if registry_path.exists() else ""
            section_re = re.compile(
                rf"^## {re.escape(kind)}: {re.escape(canonical)}\s*$\n(?:.*?)(?=^## |\Z)",
                re.M | re.S,
            )
            body_lines = "\n".join(f"- {a}" for a in combined_aliases if a != canonical)
            section = f"## {kind}: {canonical}\n" + (body_lines + "\n" if body_lines else "")
            match = section_re.search(content)
            if match:
                content = content[:match.start()] + section + content[match.end():]
            else:
                if content and not content.endswith("\n\n"):
                    content = content.rstrip("\n") + "\n\n"
                content += section
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(registry_path, content)
        return result
