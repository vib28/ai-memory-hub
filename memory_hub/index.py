from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import MemoryRecord
from .utils import text_hash
from .embeddings import LocalEmbeddingProvider, cosine_similarity

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    text TEXT NOT NULL,
    normalized_hash TEXT NOT NULL,
    kind TEXT NOT NULL,
    tag TEXT NOT NULL,
    subject TEXT NOT NULL,
    writer TEXT NOT NULL,
    date TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_hash ON memories(normalized_hash);
CREATE INDEX IF NOT EXISTS idx_memories_path ON memories(path);
CREATE INDEX IF NOT EXISTS idx_memories_kind_length ON memories(kind, length(text));

CREATE TABLE IF NOT EXISTS pending (
    proposal_id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    kind TEXT NOT NULL,
    tag TEXT NOT NULL,
    subject TEXT NOT NULL,
    writer TEXT NOT NULL,
    target_path TEXT,
    supersedes_id TEXT,
    entity_id TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    decision_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_pending_status ON pending(status, created_at);
"""

class MemoryIndex:
    def __init__(self, vault_root: Path, embedding_provider: LocalEmbeddingProvider | None = None):
        self.path = Path(vault_root) / ".memory_index.sqlite3"
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.embedding_provider = embedding_provider
        self.conn.executescript(SCHEMA)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS memory_embeddings (
                memory_id TEXT PRIMARY KEY,
                vector_json TEXT NOT NULL,
                model TEXT NOT NULL,
                content_hash TEXT NOT NULL
            )"""
        )
        self.conn.commit()
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(pending)")}
        if "payload" not in columns:
            self.conn.execute("ALTER TABLE pending ADD COLUMN payload TEXT")
            self.conn.commit()
        if "entity_id" not in columns:
            self.conn.execute("ALTER TABLE pending ADD COLUMN entity_id TEXT")
            self.conn.commit()
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(memory_id UNINDEXED, text, path, kind, tag, subject)"
            )
            self.has_fts = True
        except sqlite3.OperationalError:
            self.has_fts = False

    def close(self):
        self.conn.close()

    def rebuild(self, records: Iterable[MemoryRecord]) -> int:
        records = list(records)
        with self.conn:
            self.conn.execute("DELETE FROM memories")
            self.conn.execute("DELETE FROM memory_embeddings")
            if self.has_fts:
                self.conn.execute("DELETE FROM memory_fts")
            for r in records:
                self.upsert(r, commit=False)
        return len(records)

    def upsert(self, r: MemoryRecord, commit: bool = True) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO memories
               (memory_id,path,text,normalized_hash,kind,tag,subject,writer,date)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (r.memory_id, r.path, r.text, text_hash(r.text), r.kind, r.tag, r.subject, r.writer, r.date),
        )
        if self.has_fts:
            self.conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (r.memory_id,))
            self.conn.execute(
                "INSERT INTO memory_fts(memory_id,text,path,kind,tag,subject) VALUES(?,?,?,?,?,?)",
                (r.memory_id, r.text, r.path, r.kind, r.tag, r.subject),
            )
        if commit:
            self.conn.commit()
        self._embed_record(r)

    def _embed_record(self, record: MemoryRecord) -> None:
        if not self.embedding_provider:
            return
        try:
            vector = self.embedding_provider.embed([record.text])[0]
        except Exception:
            return
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO memory_embeddings(memory_id,vector_json,model,content_hash) VALUES(?,?,?,?)",
                (record.memory_id, json.dumps(vector), self.embedding_provider.model, text_hash(record.text)),
            )

    def remove(self, memory_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM memories WHERE memory_id=?", (memory_id,))
            self.conn.execute("DELETE FROM memory_embeddings WHERE memory_id=?", (memory_id,))
            if self.has_fts:
                self.conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))

    def by_id(self, memory_id: str):
        row = self.conn.execute("SELECT * FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def exact_hash(self, normalized_hash: str, kind: str):
        row = self.conn.execute(
            "SELECT * FROM memories WHERE normalized_hash=? AND kind=? AND tag!='superseded' LIMIT 1",
            (normalized_hash, kind),
        ).fetchone()
        return dict(row) if row else None

    def all_rows(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM memories ORDER BY path,date,memory_id")]

    def candidate_rows(self, kind: str, min_length: int, max_length: int) -> list[dict]:
        """Return only same-kind rows whose text length is in a caller-safe window."""
        rows = self.conn.execute(
            """SELECT * FROM memories
               WHERE kind=? AND tag!='superseded'
                 AND length(text) BETWEEN ? AND ?
               ORDER BY path,date,memory_id""",
            (kind, min_length, max_length),
        )
        return [dict(row) for row in rows]

    def search(self, query: str, limit: int = 10) -> list[dict]:
        limit = max(1, min(int(limit), 50))
        fts_rows: list[dict] = []
        if self.has_fts:
            tokens = [t for t in query.replace('"', ' ').split() if t]
            if tokens:
                safe = " OR ".join(f'"{t}"' for t in tokens[:12])
                try:
                    rows = self.conn.execute(
                        """SELECT m.* FROM memory_fts f
                           JOIN memories m USING(memory_id)
                           WHERE memory_fts MATCH ?
                           ORDER BY bm25(memory_fts)
                           LIMIT ?""",
                        (safe, limit),
                    ).fetchall()
                    if rows:
                        fts_rows = [dict(r) for r in rows]
                except sqlite3.OperationalError:
                    pass
        if not fts_rows:
            like = f"%{query}%"
            rows = self.conn.execute(
                """SELECT * FROM memories
                   WHERE text LIKE ? OR path LIKE ? OR subject LIKE ?
                   ORDER BY date DESC LIMIT ?""",
                (like, like, like, limit),
            ).fetchall()
            fts_rows = [dict(r) for r in rows]
        if not self.embedding_provider:
            return fts_rows[:limit]
        try:
            query_vector = self.embedding_provider.embed([query])[0]
        except Exception:
            return fts_rows[:limit]
        vector_rows = self.conn.execute(
            "SELECT memory_id, vector_json FROM memory_embeddings"
        ).fetchall()
        scores = {}
        for row in vector_rows:
            try:
                scores[row["memory_id"]] = cosine_similarity(query_vector, json.loads(row["vector_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        vector_ids = [memory_id for memory_id, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit * 3]]
        rows_by_id = {row["memory_id"]: row for row in self.all_rows()}
        ranked: dict[str, float] = {}
        for rank, row in enumerate(fts_rows):
            ranked[row["memory_id"]] = ranked.get(row["memory_id"], 0.0) + 1.0 / (rank + 1)
        for rank, memory_id in enumerate(vector_ids):
            ranked[memory_id] = ranked.get(memory_id, 0.0) + scores[memory_id] + 0.5 / (rank + 1)
        return [rows_by_id[memory_id] for memory_id, _ in sorted(ranked.items(), key=lambda item: item[1], reverse=True)[:limit] if memory_id in rows_by_id]

    def semantic_candidates(self, kind: str, threshold: float = 0.85,
                            limit: int = 200) -> list[dict]:
        """Return semantic pairs for read-only audit and human review."""
        if not self.embedding_provider:
            return []
        rows = self.conn.execute(
            """SELECT m.*, e.vector_json FROM memories m
               JOIN memory_embeddings e USING(memory_id)
               WHERE m.kind=? AND m.tag!='superseded' ORDER BY m.memory_id""",
            (kind,),
        ).fetchall()
        pairs = []
        for index, left in enumerate(rows):
            try:
                left_vector = json.loads(left["vector_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            for right in rows[index + 1:]:
                try:
                    score = cosine_similarity(left_vector, json.loads(right["vector_json"]))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if score >= threshold and left["normalized_hash"] != right["normalized_hash"]:
                    pairs.append({
                        "kind": kind,
                        "memory_ids": [left["memory_id"], right["memory_id"]],
                        "subjects": [left["subject"], right["subject"]],
                        "similarity": round(score, 4),
                    })
        pairs.sort(key=lambda item: item["similarity"], reverse=True)
        return pairs[:max(1, limit)]

    # ---- review queue ----

    def enqueue(self, candidate: dict, payload: dict | None = None) -> dict:
        proposal_id = uuid.uuid4().hex[:12]
        created_at = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """INSERT INTO pending
                   (proposal_id,text,kind,tag,subject,writer,target_path,supersedes_id,entity_id,created_at,status,payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?)""",
                (
                    proposal_id,
                    candidate["text"],
                    candidate["kind"],
                    candidate["tag"],
                    candidate["subject"],
                    candidate["writer"],
                    candidate.get("target_path"),
                    candidate.get("supersedes_id"),
                    candidate.get("entity_id"),
                    created_at,
                    json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                ),
            )
        return self.pending_by_id(proposal_id)

    def pending_by_id(self, proposal_id: str):
        row = self.conn.execute("SELECT * FROM pending WHERE proposal_id=?", (proposal_id,)).fetchone()
        return dict(row) if row else None

    def list_pending(self, status: str | None = "pending", limit: int = 200) -> list[dict]:
        if status is None:
            rows = self.conn.execute(
                "SELECT * FROM pending ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 1000)),),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM pending WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, max(1, min(limit, 1000))),
            ).fetchall()
        return [dict(r) for r in rows]

    def set_pending_status(self, proposal_id: str, status: str, note: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE pending SET status=?, decision_note=? WHERE proposal_id=?",
                (status, note, proposal_id),
            )

    def pending_duplicate(self, text: str, subject: str, kind: str):
        row = self.conn.execute(
            """SELECT * FROM pending
               WHERE status='pending' AND text=? AND subject=? AND kind=? LIMIT 1""",
            (text, subject, kind),
        ).fetchone()
        return dict(row) if row else None
