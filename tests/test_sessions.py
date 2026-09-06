import sys
import tempfile
import unittest
from pathlib import Path

from memory_hub.manager import MemoryManager


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.manager = MemoryManager(self.vault)
        self.manager.initialize(Path(__file__).resolve().parent.parent / "vault_template")

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def test_session_path_block_fts_and_project_link(self):
        result = self.manager.propose_session({
            "model": "codex", "title": "autotradag", "date": "2026-09-06T23:00:00",
            "project": "ai-memory-hub", "investigated": ["FTS indexing"],
            "learned": ["Session blocks need stable IDs"], "completed": ["Implemented sessions"],
            "next_steps": ["Add tests"],
        })
        self.assertEqual(result["status"], "stored")
        memory = result["memory"]
        self.assertEqual(memory["path"], "/sessions/ai-memory-hub/codex.md")
        content = self.manager.read("/sessions/ai-memory-hub/codex.md")
        self.assertIn("## codex-autotradag-2026-09-06-230000", content)
        self.assertIn("### Investigated", content)
        self.assertIn("#codex #2026-09-06", content)
        self.assertTrue(any(r["memory_id"] == memory["memory_id"] for r in self.manager.search("stable IDs")))
        project = result["project"]["memory"]
        self.assertEqual(project["path"], "/projects/ai-memory-hub.md")
        self.assertIn(f"[[{memory['subject']}]]", self.manager.read(project["path"]))

    def test_review_approval_preserves_session_sections(self):
        result = self.manager.propose_session({
            "model": "gemini", "title": "review", "investigated": ["One thing"],
            "learned": ["Another thing"], "completed": ["A task"], "next_steps": ["More work"],
        }, write_mode="review")
        self.assertEqual(result["status"], "queued")
        approved = self.manager.approve(result["proposal"]["proposal_id"])
        self.assertEqual(approved["status"], "stored")
        self.assertIn("### Next Steps", self.manager.read("/sessions/gemini.md"))

    def test_empty_optional_section_does_not_reject_session(self):
        result = self.manager.propose_session({
            "model": "codex", "title": "empty-next-steps", "date": "2026-09-06T23:00:00",
            "investigated": ["The session writer was tested"],
            "learned": ["Next Steps may legitimately be empty"],
            "completed": ["Added regression coverage"],
            "next_steps": [],
        }, write_mode="review")
        self.assertEqual(result["status"], "queued")


class SessionRoutingMigrationTests(unittest.TestCase):
    """#26: relocating existing writer-major blocks into the project-major layout."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = MemoryManager(Path(self.tmp.name) / "vault")
        self.manager.initialize(Path(__file__).resolve().parent.parent / "vault_template")
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def _write_legacy_file(self, model: str, blocks: str) -> Path:
        path = self.manager.vault.resolve(f"/sessions/{model}.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\ntype: session\nstatus: active\n---\n\n" + blocks, encoding="utf-8")
        return path

    LINKED = ("## claude-alpha-2026-09-01-100000\n"
              "**Model:** claude\n**Project:** [[demo]]\n\n"
              "### Investigated\n- something\n\n<!-- session:aaaaaaaaaaaa -->\n")
    UNLINKED = ("## claude-beta-2026-09-02-100000\n"
                "**Model:** claude\n**Project:** None\n\n"
                "### Investigated\n- something else\n\n<!-- session:bbbbbbbbbbbb -->\n")

    def test_dry_run_reports_moves_without_writing(self):
        import migrate_session_routing as migration
        source = self._write_legacy_file("claude", self.LINKED + "\n" + self.UNLINKED)
        before = source.read_text(encoding="utf-8")
        moves, skipped = migration.plan_moves(self.manager.vault.root)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["project"], "demo")
        self.assertEqual(skipped, [])
        self.assertEqual(source.read_text(encoding="utf-8"), before)

    def test_apply_moves_relocates_only_project_linked_blocks(self):
        import migrate_session_routing as migration
        source = self._write_legacy_file("claude", self.LINKED + "\n" + self.UNLINKED)
        moves, _ = migration.plan_moves(self.manager.vault.root)
        migration.apply_moves(self.manager, moves)

        moved = self.manager.read("/sessions/demo/claude.md")
        self.assertIn("session:aaaaaaaaaaaa", moved)
        self.assertTrue(moved.startswith("---"))
        remaining = source.read_text(encoding="utf-8")
        self.assertIn("session:bbbbbbbbbbbb", remaining)
        self.assertNotIn("session:aaaaaaaaaaaa", remaining)
        self.assertTrue(remaining.startswith("---"))

    def test_source_file_is_removed_when_every_block_moves(self):
        import migrate_session_routing as migration
        source = self._write_legacy_file("claude", self.LINKED)
        migration.apply_moves(self.manager, migration.plan_moves(self.manager.vault.root)[0])
        self.assertFalse(source.exists())

    def test_blocks_without_an_id_marker_are_skipped_not_moved(self):
        import migrate_session_routing as migration
        orphan = self.LINKED.replace("<!-- session:aaaaaaaaaaaa -->", "")
        self._write_legacy_file("claude", orphan)
        moves, skipped = migration.plan_moves(self.manager.vault.root)
        self.assertEqual(moves, [])
        self.assertEqual(len(skipped), 1)

    def test_migration_is_idempotent(self):
        import migrate_session_routing as migration
        self._write_legacy_file("claude", self.LINKED)
        migration.apply_moves(self.manager, migration.plan_moves(self.manager.vault.root)[0])
        second, _ = migration.plan_moves(self.manager.vault.root)
        self.assertEqual(second, [])
        self.assertEqual(self.manager.read("/sessions/demo/claude.md").count("## claude-alpha"), 1)

    def test_records_survive_the_move_and_reindex(self):
        import migrate_session_routing as migration
        self._write_legacy_file("claude", self.LINKED)
        migration.apply_moves(self.manager, migration.plan_moves(self.manager.vault.root)[0])
        self.manager.reindex()
        row = self.manager.index.by_id("aaaaaaaaaaaa")
        self.assertIsNotNone(row)
        self.assertEqual(row["path"], "/sessions/demo/claude.md")


if __name__ == "__main__":
    unittest.main()
