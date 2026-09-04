from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

ALLOWED_KINDS = {"profile", "preference", "person", "project", "topic", "decision"}
ALLOWED_TAGS = {"stated", "decided", "inferred", "preference", "constraint", "open", "superseded"}
ALLOWED_WRITERS = {"chatgpt", "claude", "gemini", "kimi", "cursor", "user", "other"}

@dataclass
class MemoryCandidate:
    text: str
    kind: str
    tag: str
    subject: str = "general"
    writer: str = "other"
    target_path: Optional[str] = None
    supersedes_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class MemoryRecord:
    memory_id: str
    path: str
    text: str
    kind: str
    tag: str
    subject: str
    writer: str
    date: str

    def to_dict(self) -> dict:
        return asdict(self)
