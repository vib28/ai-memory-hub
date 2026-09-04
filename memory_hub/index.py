from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import MemoryRecord
from .utils import text_hash

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

CREATE TABLE IF NOT EXISTS pending (
    proposal_id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    kind TEXT NOT NULL,
    tag TEXT NOT NULL,
    subject TEXT NOT NULL,
    writer TEXT NOT NULL,
    target_path TEXT,
    supersedes_id TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    decision_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_pending_status ON pending(status, created_at);
"""

class MemoryIndex:
    def __init__(self, vault_root: Path):
        self.path = Path(vault_root) / ".memory_index.sqlite3"
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
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

    def remove(self, memory_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM memories WHERE memory_id=?", (memory_id,))
            if self.has_fts:
                self.conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))

    def by_id(self, memory_id: str):
        row = self.conn.execute("SELECT * FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def exact_hash(self, normalized_hash: str):
        row = self.conn.execute(
            "SELECT * FROM memories WHERE normalized_hash=? AND tag!='superseded' LIMIT 1", (normalized_hash,)
        ).fetchone()
        return dict(row) if row else None

    def all_rows(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM memories ORDER BY path,date,memory_id")]

    def search(self, query: str, limit: int = 10) -> list[dict]:
        limit = max(1, min(int(limit), 50))
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
                        return [dict(r) for r in rows]
                except sqlite3.OperationalError:
                    pass
        like = f"%{query}%"
        rows = self.conn.execute(
            """SELECT * FROM memories
               WHERE text LIKE ? OR path LIKE ? OR subject LIKE ?
               ORDER BY date DESC LIMIT ?""",
            (like, like, like, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- review queue ----

    def enqueue(self, candidate: dict) -> dict:
        proposal_id = uuid.uuid4().hex[:12]
        created_at = datetime.now(timezone.utc).isoformat()
        with self.conn:
            self.conn.execute(
                """INSERT INTO pending
                   (proposal_id,text,kind,tag,subject,writer,target_path,supersedes_id,created_at,status)
                   VALUES (?,?,?,?,?,?,?,?,?,'pending')""",
                (
                    proposal_id,
                    candidate["text"],
                    candidate["kind"],
                    candidate["tag"],
                    candidate["subject"],
                    candidate["writer"],
                    candidate.get("target_path"),
                    candidate.get("supersedes_id"),
                    created_at,
                ),
            )
        return self.pending_by_id(proposal_id)

    def pending_by_id(self, proposal_id: str):
        row = self.conn.execute("SELECT * FROM pending WHERE proposal_id=?", (proposal_id,)).fetchone()
        return dict(row) if row else None

    def list_pending(self, status: str = "pending", limit: int = 200) -> list[dict]:
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
