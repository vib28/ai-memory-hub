from __future__ import annotations

import argparse
import json
from pathlib import Path

from .extractor import extract_candidates
from .history import history_status, initialize_history
from .manager import MemoryManager
from .models import MemoryCandidate

def jprint(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AI Memory Hub")
    p.add_argument("--vault", required=True, help="Path to Obsidian memory vault")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    sub.add_parser("audit")
    sub.add_parser("reindex")
    sub.add_parser("history-init")
    sub.add_parser("history-status")

    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)

    r = sub.add_parser("read")
    r.add_argument("path")

    a = sub.add_parser("propose")
    a.add_argument("--writer", required=True)
    a.add_argument("--kind", required=True)
    a.add_argument("--tag", required=True)
    a.add_argument("--subject", default="general")
    a.add_argument("--target-path")
    a.add_argument("--text", required=True)

    f = sub.add_parser("forget")
    f.add_argument("memory_id")

    su = sub.add_parser("supersede")
    su.add_argument("old_memory_id")
    su.add_argument("--writer", required=True)
    su.add_argument("--kind", required=True)
    su.add_argument("--tag", required=True)
    su.add_argument("--subject", default="general")
    su.add_argument("--target-path")
    su.add_argument("--text", required=True)

    ing = sub.add_parser("ingest")
    ing.add_argument("transcript_file")
    ing.add_argument("--writer", required=True)

    return p

def main():
    args = build_parser().parse_args()
    manager = MemoryManager(args.vault)
    try:
        if args.command == "init":
            template = Path(__file__).resolve().parent.parent / "vault_template"
            jprint(manager.initialize(template))
        elif args.command == "audit":
            jprint(manager.audit())
        elif args.command == "reindex":
            jprint({"indexed": manager.reindex()})
        elif args.command == "history-init":
            jprint(initialize_history(args.vault))
        elif args.command == "history-status":
            jprint(history_status(args.vault))
        elif args.command == "search":
            jprint(manager.search(args.query, args.limit))
        elif args.command == "read":
            print(manager.read(args.path))
        elif args.command == "propose":
            jprint(manager.propose(MemoryCandidate(
                text=args.text,
                kind=args.kind,
                tag=args.tag,
                subject=args.subject,
                writer=args.writer,
                target_path=args.target_path,
            )))
        elif args.command == "forget":
            jprint(manager.forget(args.memory_id))
        elif args.command == "supersede":
            jprint(manager.supersede(args.old_memory_id, MemoryCandidate(
                text=args.text,
                kind=args.kind,
                tag=args.tag,
                subject=args.subject,
                writer=args.writer,
                target_path=args.target_path,
            )))
        elif args.command == "ingest":
            transcript = Path(args.transcript_file).read_text(encoding="utf-8")
            candidates = extract_candidates(transcript)
            results = []
            for raw in candidates:
                try:
                    c = MemoryCandidate(
                        text=str(raw["text"]),
                        kind=str(raw["kind"]),
                        tag=str(raw["tag"]),
                        subject=str(raw.get("subject", "general")),
                        writer=args.writer,
                    )
                    results.append(manager.propose(c))
                except KeyError as exc:
                    results.append({"status": "rejected", "reason": f"missing extractor field: {exc}"})
            jprint({"candidates": len(candidates), "results": results})
    finally:
        manager.close()

if __name__ == "__main__":
    main()
