"""Import historical session summaries through the public MCP write boundary."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


REQUIRED = ("title", "investigated", "learned", "completed", "next_steps")


def load_sessions(path: Path) -> list[dict]:
    value = json.loads(path.read_text(encoding="utf-8"))
    sessions = value.get("sessions") if isinstance(value, dict) else value
    if not isinstance(sessions, list) or not all(isinstance(item, dict) for item in sessions):
        raise ValueError("input must be a JSON array or an object containing a sessions array")
    for index, session in enumerate(sessions):
        missing = [field for field in REQUIRED if field not in session]
        if missing:
            raise ValueError(f"session {index} is missing: {', '.join(missing)}")
    return sessions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--writer", default="other")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        sessions = load_sessions(args.input)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}))
        return 2
    if args.dry_run:
        print(json.dumps({"status": "dry_run", "would_import": len(sessions),
                          "titles": [str(item["title"]) for item in sessions]}, ensure_ascii=False))
        return 0

    os.environ["AI_MEMORY_VAULT"] = str(Path(args.vault))
    os.environ["MEMORY_WRITER"] = args.writer
    from memory_hub.mcp_server import memory_audit, session_write

    results = []
    for session in sessions:
        payload = dict(session)
        payload.setdefault("project", None)
        payload.setdefault("session_date", None)
        try:
            result = session_write(
                title=str(payload["title"]),
                investigated=list(payload["investigated"]),
                learned=list(payload["learned"]),
                completed=list(payload["completed"]),
                next_steps=list(payload["next_steps"]),
                project=payload["project"],
                session_date=payload["session_date"],
            )
        except Exception as exc:
            result = {"status": "rejected", "reason": str(exc)}
        results.append({"title": payload["title"], "result": result})

    audit = memory_audit()
    successful = sum(item["result"].get("status") in {"stored", "queued", "duplicate"}
                     for item in results)
    status = "complete" if audit.get("healthy", False) else "verification_failed"
    print(json.dumps({"status": status, "imported": successful,
                      "rejected": len(results) - successful,
                      "results": results, "audit": audit}, ensure_ascii=False))
    return 0 if status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
