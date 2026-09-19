from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .extractor import extract_from_transcript
from .github_export import configure, run_once
from .history import commit_vault_change, history_status, initialize_history
from .hooks import (
    install_claude_hook,
    install_codex_hook,
    install_hermes_hook,
    install_hook,
    install_nested_hook,
    install_toml_hook,
    uninstall_claude_hook,
    uninstall_codex_hook,
    uninstall_hermes_hook,
    uninstall_hook,
    uninstall_nested_hook,
    uninstall_toml_hook,
)
from .manager import MemoryManager
from .models import MemoryCandidate
from .security import (
    VaultEncryption,
    VaultEncryptionError,
    generate_encryption_key,
    get_vault_encryption,
)


def cmd_vault_key(args):
    """Generate and print a fresh 256-bit encryption key."""
    print(generate_encryption_key())


def cmd_vault_encrypt(args):
    """Encrypt every *.md file in the vault (writes *.md.enc companions)."""
    import sys
    vault = Path(args.vault).expanduser().resolve()
    enc = get_vault_encryption(vault)
    if args.key:
        enc = VaultEncryption(args.key)
    if not enc.enabled:
        raise SystemExit("no key: pass --key or set VAULT_ENCRYPTION_KEY")

    changed = 0
    skipped = 0
    for md in sorted(vault.rglob("*.md")):
        if ".obsidian" in md.parts:
            continue
        enc_path = md.with_suffix(md.suffix + ".enc")
        if enc_path.exists():
            skipped += 1
            continue
        try:
            content = md.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"  skip {md}: {exc}", file=sys.stderr)
            continue
        from .security import encrypt_data
        enc_path.write_bytes(encrypt_data(content, enc._key))
        changed += 1
    jprint({"encrypted": changed, "skipped_already_encrypted": skipped})


def cmd_vault_decrypt(args):
    """Decrypt every *.md.enc file back to plaintext *.md."""
    import sys
    vault = Path(args.vault).expanduser().resolve()
    enc = get_vault_encryption(vault)
    if args.key:
        enc = VaultEncryption(args.key)
    if not enc.enabled:
        raise SystemExit("no key: pass --key or set VAULT_ENCRYPTION_KEY")

    from .security import decrypt_data

    changed = 0
    skipped = 0
    for enc_path in sorted(vault.rglob("*.md.enc")):
        if ".obsidian" in enc_path.parts:
            continue
        md = enc_path.with_suffix("")  # strip .enc
        try:
            blob = enc_path.read_bytes()
            plaintext = decrypt_data(blob, enc._key).decode("utf-8")
        except (OSError, VaultEncryptionError) as exc:
            print(f"  skip {enc_path}: {exc}", file=sys.stderr)
            skipped += 1
            continue
        md.write_text(plaintext, encoding="utf-8")
        changed += 1
    jprint({"decrypted": changed, "skipped_errors": skipped})


def cmd_vault_status(args):
    """Show how many .enc companions exist vs plaintext-only files."""
    vault = Path(args.vault).expanduser().resolve()
    encrypted = 0
    plaintext_only = 0
    for md in sorted(vault.rglob("*.md")):
        if ".obsidian" in md.parts:
            continue
        if md.with_suffix(md.suffix + ".enc").exists():
            encrypted += 1
        else:
            plaintext_only += 1
    jprint({"encrypted": encrypted, "plaintext_only": plaintext_only})

# ---------------------------------------------------------------------------
# Doctor / capabilities imports (lazy to keep CLI startup fast)
# ---------------------------------------------------------------------------
_CAPABILITIES_IMPORTS = None


def _capabilities():
    global _CAPABILITIES_IMPORTS
    if _CAPABILITIES_IMPORTS is None:
        from .capabilities import (
            ALL_EVENTS,
            CLIENT_PROFILES,
            EVENT_LABELS,
            check_encryption_status,
            check_mcp_connectivity,
            gather_capabilities,
        )
        _CAPABILITIES_IMPORTS = {
            "ALL_EVENTS": ALL_EVENTS,
            "EVENT_LABELS": EVENT_LABELS,
            "CLIENT_PROFILES": CLIENT_PROFILES,
            "check_encryption_status": check_encryption_status,
            "check_mcp_connectivity": check_mcp_connectivity,
            "gather_capabilities": gather_capabilities,
        }
    return _CAPABILITIES_IMPORTS


def jprint(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _quote_for_shell(value: str) -> str:
    text = str(value)
    if text and all(ch.isalnum() or ch in "-_=./:\\" for ch in text):
        return text
    return '"' + text.replace('"', '\\"') + '"'


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
    ge = sub.add_parser("github-export-config")
    ge.add_argument("--repo")
    ge.add_argument("--visibility", choices=("public", "private", "internal"))
    ge_mode = ge.add_mutually_exclusive_group(required=True)
    ge_mode.add_argument("--enable", action="store_true")
    ge_mode.add_argument("--disable", action="store_true")
    gx = sub.add_parser("github-export")
    gx.add_argument("--group")
    gx.add_argument("--once", action="store_true")
    hi = sub.add_parser("hooks-install")
    hi.add_argument("--settings", required=True)
    hi.add_argument("--event", default="PostToolUse")
    hi.add_argument("--command", dest="hook_command", default="ai-memory-hook")
    hi.add_argument("--arg", action="append", default=None)
    hi.add_argument("--format", choices=("claude", "nested", "kimi-toml", "codex", "hermes-yaml"),
                    default="claude")
    hi.add_argument("--matcher", default="*")
    hi.add_argument("--timeout", type=int, default=None)
    hi.add_argument("--additional-context-limit", type=int)
    hu = sub.add_parser("hooks-uninstall")
    hu.add_argument("--settings", required=True)
    hu.add_argument("--format", choices=("claude", "nested", "kimi-toml", "codex", "hermes-yaml"),
                    default="claude")
    hu.add_argument("--command", dest="hook_command")

    # --- doctor subcommand ---
    dr = sub.add_parser("doctor", help="Diagnose hub and client health")
    dr.add_argument("--clients", action="store_true",
                    help="Report per-client capability health")
    dr.add_argument("--json", action="store_true",
                    help="Output raw JSON instead of a formatted report")
    dr.add_argument("--vault", default=None,
                    help="Vault path (defaults to AI_MEMORY_VAULT)")

    # --- vault encryption subcommands ---
    sub.add_parser("vault-key", help="Generate a new random 256-bit encryption key")

    ve = sub.add_parser("vault-encrypt", help="Encrypt all *.md files in the vault")
    ve.add_argument("--key", help="Base64 32-byte key (default: VAULT_ENCRYPTION_KEY env var)")

    vd = sub.add_parser("vault-decrypt", help="Decrypt all *.md.enc files back to plaintext")
    vd.add_argument("--key", help="Base64 32-byte key (default: VAULT_ENCRYPTION_KEY env var)")

    sub.add_parser("vault-status", help="Count encrypted vs plaintext files")

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


def _doctor_report(args) -> dict:
    cap = _capabilities()
    vault = args.vault or "."
    capabilities = cap["gather_capabilities"](vault, include_hermes=True)
    mcp = cap["check_mcp_connectivity"]()
    encryption = cap["check_encryption_status"]()
    return {
        "capabilities": capabilities,
        "mcp": mcp,
        "encryption": encryption,
    }


def _print_doctor_report(report: dict) -> None:
    cap = report["capabilities"]
    mcp = report["mcp"]
    enc = report["encryption"]
    all_events = cap["all_events"]
    cap["event_labels"]

    print("=" * 72)
    print("AI Memory Hub — doctor report")
    print(f"Generated at: {cap.get('generated_at', '?')}")
    print("=" * 72)

    # Worker
    worker = cap.get("worker", {})
    print(f"\n[Worker] status: {worker.get('status', '?')}")
    if worker.get("last_run_at"):
        print(f"  last run:        {worker['last_run_at']}")
    if worker.get("last_success_at"):
        print(f"  last success:    {worker['last_success_at']}")
    if worker.get("backlog") is not None:
        print(f"  backlog:         {worker['backlog']} pending")
    if worker.get("last_error"):
        print(f"  last error:      {worker['last_error']}")

    # MCP
    print(f"\n[MCP Server] status: {mcp.get('status', '?')}")
    print(f"  registered tools: {mcp.get('tool_count', '?')}")
    if mcp.get("tools"):
        for t in mcp["tools"]:
            print(f"    - {t}")
    if mcp.get("error"):
        print(f"  error: {mcp['error']}")

    # Encryption / secrets
    print("\n[Security]")
    print(f"  encryption at rest:    {enc.get('encryption_at_rest', False)}")
    print(f"  secret detection:      {'active' if enc.get('secret_detection_active') else 'INACTIVE'}")
    print(f"  secret patterns:       {enc.get('secret_pattern_count', 0)}")
    print(f"  note:                  {enc.get('note', '')}")

    # Per-client
    print(f"\n[Clients] {len(cap.get('clients', []))} configured")
    for client in cap.get("clients", []):
        print(f"\n  ── {client['display_name']} ({client['key']}) ──")
        hook = "installed ✓" if client["hook_installed"] else "missing ✗"
        print(f"    hook: {hook}  (format: {client['hook_format']})")
        if client.get("hook_events"):
            print(f"    hook events: {', '.join(client['hook_events'])}")
        if client.get("hook_error"):
            print(f"    hook error:  {client['hook_error']}")
        if client.get("settings_path"):
            print(f"    settings:    {client['settings_path']}")
        buf = client.get("buffer", {})
        if buf.get("total_observations", 0):
            print(f"    observations: {buf['total_observations']}")
            print(f"    event types:  {buf['supported_event_count']}")
            print(f"    last capture: {buf.get('last_capture', '?')}")
            print(f"    pending:      {buf['pending_buffer_depth']}")
        else:
            print("    buffer:      no observations yet")

    # Event support matrix
    print("\n[Event Support Matrix]")
    print(f"  {'Client':<16}", end="")
    for ev in all_events:
        short = ev[:6]
        print(f" {short:>6}", end="")
    print()
    print(f"  {'-' * 16}", end="")
    for _ in all_events:
        print(f" {'-' * 6}", end="")
    print()
    for client in cap.get("clients", []):
        buf_events = set(client.get("buffer", {}).get("events", {}).keys())
        print(f"  {client['key']:<16}", end="")
        for ev in all_events:
            mark = "  ✓" if ev in buf_events else "  ·"
            print(f" {mark:>6}", end="")
        print()
    print()


def main():
    args = build_parser().parse_args()
    if args.command in {"hooks-install", "hooks-uninstall"}:
        if args.command == "hooks-install":
            joined = " ".join([_quote_for_shell(args.hook_command), *map(_quote_for_shell, args.arg or [])])
            if args.format == "nested":
                jprint(install_nested_hook(args.settings, event=args.event,
                                           command=joined, matcher=args.matcher))
            elif args.format == "kimi-toml":
                jprint(install_toml_hook(args.settings, event=args.event, command=joined,
                                         matcher=None if args.matcher in {"*", ""} else args.matcher,
                                         timeout=args.timeout))
            elif args.format == "hermes-yaml":
                jprint(install_hermes_hook(args.settings, event=args.event, command=joined,
                                           timeout=args.timeout or 20,
                                           matcher=None if args.matcher in {"*", ""} else args.matcher))
            elif args.format == "codex":
                jprint(install_codex_hook(args.settings, event=args.event,
                                          command=joined, matcher=args.matcher,
                                          additional_context_limit=args.additional_context_limit))
            elif args.format == "claude":
                jprint(install_claude_hook(args.settings, event=args.event,
                                           command=args.hook_command, matcher=args.matcher,
                                           args=args.arg))
            else:
                jprint(install_hook(args.settings, event=args.event, command=args.hook_command, args=args.arg))
        else:
            hook_format = getattr(args, "format", "claude")
            command = args.hook_command
            if hook_format == "nested":
                jprint(uninstall_nested_hook(args.settings, command=command))
            elif hook_format == "kimi-toml":
                jprint(uninstall_toml_hook(args.settings, command=command))
            elif hook_format == "hermes-yaml":
                jprint(uninstall_hermes_hook(args.settings, command=command))
            elif hook_format == "codex":
                jprint(uninstall_codex_hook(args.settings, command=command))
            elif hook_format == "claude":
                jprint(uninstall_claude_hook(args.settings, command=command))
            else:
                jprint(uninstall_hook(args.settings, command=command))
        return

    if args.command == "doctor":
        report = _doctor_report(args)
        if getattr(args, "json", False):
            jprint(report)
        else:
            _print_doctor_report(report)
        return

    if args.command == "vault-key":
        cmd_vault_key(args)
        return

    if not args.vault:
        raise SystemExit("--vault is required for this command")
    if args.command == "vault-encrypt":
        cmd_vault_encrypt(args)
        return
    if args.command == "vault-decrypt":
        cmd_vault_decrypt(args)
        return
    if args.command == "vault-status":
        cmd_vault_status(args)
        return
    if args.command == "history-init":
        jprint(initialize_history(args.vault))
        return
    if args.command == "history-status":
        jprint(history_status(args.vault))
        return
    if args.command == "history-commit":
        jprint(commit_vault_change(args.vault, args.session_id, args.paths))
        return
    if args.command == "github-export-config":
        jprint(configure(args.vault, repo=args.repo, visibility=args.visibility, enabled=args.enable))
        return
    if args.command == "github-export":
        jprint(run_once(args.vault, args.group))
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
            transcript_hash = hashlib.sha256(transcript.encode("utf-8")).hexdigest()[:16]
            candidates = extract_from_transcript(transcript)
            results = []
            for raw in candidates:
                try:
                    c = MemoryCandidate(
                        text=str(raw["text"]),
                        kind=str(raw["kind"]),
                        tag=str(raw["tag"]),
                        subject=str(raw.get("subject", "general")),
                        writer=args.writer,
                        evidence_ids=[transcript_hash],
                    )
                    results.append(manager.propose(c))
                except KeyError as exc:
                    results.append({"status": "rejected", "reason": f"missing extractor field: {exc}"})
            jprint({"candidates": len(candidates), "results": results})
    finally:
        manager.close()


if __name__ == "__main__":
    main()
