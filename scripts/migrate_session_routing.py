"""Move existing session blocks from the writer-major layout to project-major (#26).

`/sessions/<model>.md` -> `/sessions/<project>/<model>.md`, keyed on each block's
`**Project:**` link. Blocks that name no project stay where they are, which is the
canonical location for them under the new routing too.

Maintenance code: it relocates blocks that are already in the vault and proposes no new
memory, so it does not cross the client boundary #21 governs. Run with --dry-run first.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_hub.manager import MemoryManager
from memory_hub.utils import atomic_write, slugify
from memory_hub.vault import SESSION_ID_RE, SESSION_RE, dump_frontmatter, parse_frontmatter

PROJECT_RE = re.compile(r"^\*\*Project:\*\*\s*\[\[(?P<project>[^\]]+)\]\]\s*$", re.M)


def plan_moves(vault_root: Path) -> tuple[list[dict], list[str]]:
    """Return (moves, skipped). Each move records source, destination and block text."""
    sessions_dir = vault_root / "sessions"
    moves: list[dict] = []
    skipped: list[str] = []
    if not sessions_dir.exists():
        return moves, skipped
    for path in sorted(sessions_dir.glob("*.md")):
        model = path.stem
        _, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        for block in SESSION_RE.finditer(body):
            text = block.group(0).rstrip()
            slug = block.group("slug")
            if not SESSION_ID_RE.search(block.group("body")):
                skipped.append(f"{path.name}:{slug} (no session id marker — see #24)")
                continue
            project = PROJECT_RE.search(block.group("body"))
            if not project:
                continue
            moves.append({
                "source": path,
                "slug": slug,
                "model": model,
                "project": slugify(project.group("project")),
                "block": text,
            })
    return moves, skipped


def apply_moves(manager: MemoryManager, moves: list[dict]) -> None:
    by_source: dict[Path, list[dict]] = {}
    for move in moves:
        by_source.setdefault(move["source"], []).append(move)

    for source, group in by_source.items():
        relocated = {move["slug"] for move in group}
        meta, body = parse_frontmatter(source.read_text(encoding="utf-8"))
        kept = [b.group(0).rstrip() for b in SESSION_RE.finditer(body)
                if b.group("slug") not in relocated]
        for move in group:
            destination = manager.vault.canonical_path(
                "session", move["model"], project=move["project"])
            manager.vault.append_session_block(
                destination, move["block"], writer=move["model"])
            manager.vault.ensure_index_entry(
                destination, "session",
                f"Session summaries for {move['model']} on {move['project']}")
        if kept:
            atomic_write(source, dump_frontmatter(meta) + "\n" + "\n\n".join(kept) + "\n")
        else:
            source.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would move and write nothing")
    args = parser.parse_args()

    manager = MemoryManager(args.vault)
    try:
        moves, skipped = plan_moves(manager.vault.root)
        for move in moves:
            destination = manager.vault.canonical_path(
                "session", move["model"], project=move["project"])
            print(f"  /sessions/{move['model']}.md :: {move['slug']} -> {destination}")
        for note in skipped:
            print(f"  skipped {note}")
        if args.dry_run:
            print(f"dry run: {len(moves)} block(s) would move, {len(skipped)} skipped")
            return 0
        if moves:
            apply_moves(manager, moves)
        indexed = manager.reindex()
        print(f"moved {len(moves)} block(s), skipped {len(skipped)}, reindexed {indexed} record(s)")
        return 0
    finally:
        manager.close()


if __name__ == "__main__":
    raise SystemExit(main())
