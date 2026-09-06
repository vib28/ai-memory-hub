from __future__ import annotations

import argparse
import json
from pathlib import Path

from .extractor import extract_candidates
from .history import commit_vault_change, history_status, initialize_history
from .hooks import (
    install_hook,
    install_codex_hook,
    install_nested_hook,
    install_toml_hook,
    uninstall_hook,
    uninstall_codex_hook,
    uninstall_nested_hook,
    uninstall_toml_hook,
)
from .manager import MemoryManager
from .models import MemoryCandidate

def jprint(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AI Memory Hub")
    p.add_argument("--vault", help="Path to Obsidian memory vault")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    sub.add_parser("audit")
    sub.add_parser("project-audit")
    sa = sub.add_parser("subject-audit")
    sa.add_argument("--kind", action="append", dest="kinds",
                     help="Limit to this kind (repeatable); default is every kind.")
    pl = sub.add_parser("project-link")
    pl.add_argument("--source", required=True)
    pl.add_argument("--target", required=True)
    pl.add_argument("--apply", action="store_true")
    el = sub.add_parser("entity-alias-link")
    el.add_argument("--kind", required=True, choices=["preference", "profile"])
    el.add_argument("--source", required=True)
    el.add_argument("--target", required=True)
    el.add_argument("--apply", action="store_true")
    sub.add_parser("reindex")
    sub.add_parser("history-init")
    sub.add_parser("history-status")
    hc = sub.add_parser("history-commit")
    hc.add_argument("session_id")
    hc.add_argument("paths", nargs="+")
    hi = sub.add_parser("hooks-install")
    hi.add_argument("--settings", required=True)
    hi.add_argument("--event", default="PostToolUse")
    hi.add_argument("--command", dest="hook_command", default="ai-memory-hook")
    hi.add_argument("--arg", action="append", default=[])
    hi.add_argument("--format", choices=("claude", "nested", "kimi-toml", "codex"), default="claude")
    hi.add_argument("--matcher", default="*")
    hu = sub.add_parser("hooks-uninstall")
    hu.add_argument("--settings", required=True)
    hu.add_argument("--format", choices=("claude", "nested", "kimi-toml", "codex"), default="claude")
    hu.add_argument("--command", dest="hook_command", default="ai-memory-hook")

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
    a.add_argument("--entity-id")
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
    su.add_argument("--entity-id")
    su.add_argument("--target-path")
    su.add_argument("--text", required=True)

    ing = sub.add_parser("ingest")
    ing.add_argument("transcript_file")
    ing.add_argument("--writer", required=True)

    return p

def main():
    args = build_parser().parse_args()
    if args.command in {"hooks-install", "hooks-uninstall"}:
        if args.command == "hooks-install":
            if args.format == "nested":
                jprint(install_nested_hook(args.settings, event=args.event,
                                           command=args.hook_command, matcher=args.matcher))
            elif args.format == "kimi-toml":
                jprint(install_toml_hook(args.settings, event=args.event, command=args.hook_command))
            elif args.format == "codex":
                jprint(install_codex_hook(args.settings, event=args.event,
                                          command=args.hook_command, matcher=args.matcher))
            else:
                jprint(install_hook(args.settings, event=args.event, command=args.hook_command, args=args.arg))
        else:
            hook_format = getattr(args, "format", "claude")
            if hook_format == "nested":
                jprint(uninstall_nested_hook(args.settings))
            elif hook_format == "kimi-toml":
                jprint(uninstall_toml_hook(args.settings))
            elif hook_format == "codex":
                jprint(uninstall_codex_hook(args.settings, command=args.hook_command))
            else:
                jprint(uninstall_hook(args.settings))
        return
    if not args.vault:
        raise SystemExit("--vault is required for this command")
    if args.command == "history-init":
        jprint(initialize_history(args.vault))
        return
    if args.command == "history-status":
        jprint(history_status(args.vault))
        return
    if args.command == "history-commit":
        jprint(commit_vault_change(args.vault, args.session_id, args.paths))
        return
    manager = MemoryManager(args.vault)
    try:
        if args.command == "init":
            template = Path(__file__).resolve().parent.parent / "vault_template"
            jprint(manager.initialize(template))
        elif args.command == "audit":
            jprint(manager.audit())
        elif args.command == "project-audit":
            jprint(manager.project_audit())
        elif args.command == "subject-audit":
            jprint(manager.subject_audit(args.kinds))
        elif args.command == "project-link":
            jprint(manager.project_link(args.source, args.target, apply=args.apply))
        elif args.command == "entity-alias-link":
            jprint(manager.entity_alias_link(args.kind, args.source, args.target, apply=args.apply))
        elif args.command == "reindex":
            jprint({"indexed": manager.reindex()})
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
                entity_id=args.entity_id,
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
                entity_id=args.entity_id,
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
