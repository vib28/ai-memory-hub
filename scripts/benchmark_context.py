"""Measure bounded context size and retrieval quality on deterministic fixtures."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from memory_hub.manager import MemoryManager
from memory_hub.models import MemoryRecord


def _token_counter():
    try:
        import tiktoken  # type: ignore[import-not-found]
    except ImportError:
        return None, "tiktoken is not installed; token counts are unavailable"
    encoder = tiktoken.get_encoding("cl100k_base")
    return lambda text: len(encoder.encode(text)), "tiktoken cl100k_base"


def _size_metrics(text: str, counter) -> dict[str, Any]:
    return {
        "characters": len(text),
        "words": len(text.split()),
        "tokens": counter(text) if counter else None,
    }


def measure(size: int, *, max_chars: int = 4000) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ai-memory-context-") as temporary:
        manager = MemoryManager(Path(temporary))
        relevant_ids: list[str] = []
        try:
            for index in range(size):
                project = f"project-{index % 5}"
                memory_id = f"fixture-{index:06d}"
                text = (
                    f"{project} uses local SQLite memory and Markdown for durable context. "
                    f"Fixture record {index} preserves reviewable project history."
                )
                manager.index.upsert(MemoryRecord(
                    memory_id, f"/projects/{project}-{index}.md", text, "topic", "stated",
                    project, "other", f"2026-01-{(index % 28) + 1:02d}"
                ))
                if index % 5 == 0:
                    relevant_ids.append(memory_id)

            all_text = "\n".join(row["text"] for row in manager.index.all_rows())
            query = "project-0 local SQLite"
            started = time.perf_counter()
            baseline_text = all_text
            baseline_latency = time.perf_counter() - started

            started = time.perf_counter()
            context = manager.context_prime(
                project="project-0", query="local SQLite", limit=10, max_chars=max_chars
            )
            optimized_latency = time.perf_counter() - started
            optimized_text = json.dumps(context["memories"], ensure_ascii=False)

            search_results: dict[int, list[str]] = {}
            for limit in (3, 10):
                search_results[limit] = [
                    row["memory_id"] for row in manager.search(query, limit=limit)
                ]
            precision = {
                f"precision_at_{limit}": round(
                    sum(memory_id in relevant_ids for memory_id in ids) / max(1, len(ids)),
                    4,
                )
                for limit, ids in search_results.items()
            }
            counter, counter_note = _token_counter()
            return {
                "records": size,
                "query": query,
                "baseline": {
                    **_size_metrics(baseline_text, counter),
                    "latency_seconds": round(baseline_latency, 8),
                },
                "optimized_context": {
                    **_size_metrics(optimized_text, counter),
                    "latency_seconds": round(optimized_latency, 8),
                    "selected_memories": len(context["memories"]),
                    "truncated": context["truncated"],
                },
                "retrieval": precision,
                "token_counter": counter_note,
            }
        finally:
            manager.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[50, 200, 1000])
    parser.add_argument("--max-chars", type=int, default=4000)
    args = parser.parse_args()
    print(json.dumps([measure(size, max_chars=args.max_chars) for size in args.sizes], indent=2))


if __name__ == "__main__":
    main()
