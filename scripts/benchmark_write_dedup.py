"""Measure safe write-time duplicate candidate pruning."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import memory_hub.manager as manager_module
from memory_hub.manager import MemoryCandidate, MemoryManager


def measure(size: int) -> dict[str, float | int]:
    with tempfile.TemporaryDirectory(prefix="ai-memory-dedup-") as temporary:
        manager = MemoryManager(Path(temporary))
        for index in range(size):
            manager.propose(MemoryCandidate(
                text=(f"Session record {index:06d}. " + "stable context " * (1 + index % 8)),
                kind="topic", tag="stated", subject=f"record-{index}", writer="other",
            ))
        try:
            candidate = "Session record candidate. " + "stable context " * 4
            comparisons = [0]
            original_matcher = manager_module.SequenceMatcher

            def counting_matcher(*args, **kwargs):
                comparisons[0] += 1
                return original_matcher(*args, **kwargs)

            manager_module.SequenceMatcher = counting_matcher
            started = time.perf_counter()
            try:
                manager._best_match(candidate, "topic")
            finally:
                manager_module.SequenceMatcher = original_matcher
            elapsed = time.perf_counter() - started
            return {
                "records": size,
                "sequence_matcher_comparisons": comparisons[0],
                "elapsed_seconds": round(elapsed, 6),
            }
        finally:
            manager.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 500, 1000])
    args = parser.parse_args()
    print(json.dumps([measure(size) for size in args.sizes], indent=2))


if __name__ == "__main__":
    main()
