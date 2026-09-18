from __future__ import annotations

from dataclasses import dataclass, asdict, field

ALLOWED_KINDS = {"profile", "preference", "person", "project", "topic", "decision", "session"}
ALLOWED_TAGS = {"stated", "decided", "inferred", "preference", "constraint", "open", "superseded"}
ALLOWED_WRITERS = {"chatgpt", "claude", "codex", "gemini", "kimi", "qwen", "cursor", "hermes", "user", "other"}

# Kinds where a subject should hold one current answer (e.g. "primary OS"), so two
# differently-worded active entries for the same subject really are contradictory.
# The other kinds (project, topic, person, decision) are logs that legitimately
# accumulate many distinct, non-conflicting facts about the same subject over time.
SINGLETON_KINDS = {"profile", "preference"}

@dataclass
class MemoryCandidate:
    text: str
    kind: str
    tag: str
    subject: str = "general"
    writer: str = "other"
    target_path: str | None = None
    supersedes_id: str | None = None
    entity_id: str | None = None
    evidence_ids: list[str] = field(default_factory=list)

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
