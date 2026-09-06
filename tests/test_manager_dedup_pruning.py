from __future__ import annotations

from memory_hub.manager import MemoryCandidate, MemoryManager


def test_length_pruning_preserves_possible_review_match(tmp_path):
    manager = MemoryManager(tmp_path)
    try:
        manager.propose(MemoryCandidate(
            text="A stable project decision is to keep Markdown canonical.",
            kind="topic", tag="stated", subject="canonical-store", writer="other",
        ))

        row, score = manager._best_match(
            "A stable project decision is to keep Markdown canonical, updated.",
            "topic",
        )

        assert row is not None
        assert score >= manager.DUPLICATE_UPDATE_BAND
    finally:
        manager.close()


def test_length_pruning_skips_impossible_short_record(tmp_path):
    manager = MemoryManager(tmp_path)
    try:
        manager.propose(MemoryCandidate(
            text="x" * 10,
            kind="topic", tag="stated", subject="short", writer="other",
        ))

        row, score = manager._best_match("x" * 100, "topic")

        assert row is None
        assert score == 0.0
    finally:
        manager.close()
