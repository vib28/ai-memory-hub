"""Propose missing preference rules for historical pattern matches."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_hub.patterns import load_patterns


def _matches(path: Path, trigger: str) -> bool:
    terms = [part.strip().lower() for part in trigger.split(",") if part.strip()]
    content = path.read_text(encoding="utf-8")
    return any(term in content.lower() for term in terms)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--writer", default="user")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    vault = Path(args.vault)
    try:
        patterns = load_patterns(vault / "patterns.md")
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}))
        return 2
    pattern = patterns.get("regression")
    if not pattern:
        print(json.dumps({"status": "complete", "queued": 0, "skipped": 0,
                          "reason": "regression pattern not found"}))
        return 0

    candidates = []
    projects_dir = vault / "projects"
    paths = sorted(projects_dir.glob("*.md")) if projects_dir.exists() else []
    for path in paths:
        if _matches(path, pattern["trigger"]):
            subject = path.stem
            candidates.append({
                "text": f"{pattern['preference rule']} [[{subject}]]",
                "subject": subject,
                "path": str(path),
            })

    if args.dry_run:
        print(json.dumps({"status": "dry_run", "would_propose": len(candidates),
                          "candidates": candidates}, ensure_ascii=False))
        return 0

    # Configure the public MCP tool before importing its module. The tool applies the
    # same review/auto policy as every other client and owns the manager instance.
    os.environ["AI_MEMORY_VAULT"] = str(vault)
    os.environ["MEMORY_WRITER"] = args.writer
    from memory_hub.mcp_server import memory_propose

    results = []
    for candidate in candidates:
        try:
            result = memory_propose(
                text=candidate["text"], kind="preference", tag="preference",
                subject=candidate["subject"],
            )
        except ValueError as exc:
            result = {"status": "rejected", "reason": str(exc)}
        results.append({"path": candidate["path"], "result": result})
    queued = sum(item["result"].get("status") in {"queued", "stored"} for item in results)
    skipped = len(results) - queued
    print(json.dumps({"status": "complete", "queued": queued, "skipped": skipped,
                      "results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
