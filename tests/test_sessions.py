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

    def _store(self, **overrides):
        payload = {"model": "claude", "title": "routine", "date": "2026-09-06T10:00:00",
                   "project": None, "investigated": ["a thing"], "learned": [],
                   "completed": [], "next_steps": []}
        payload.update(overrides)
        return self.manager.propose_session(payload)

    # ---- #26 routing ----

    def test_session_without_project_stays_writer_major(self):
        result = self._store(model="qwen", project=None)
        self.assertEqual(result["memory"]["path"], "/sessions/qwen.md")

    def test_sessions_for_two_projects_are_separate_files(self):
        one = self._store(title="alpha", project="alpha-app")
        two = self._store(title="beta", project="beta-app")
        self.assertEqual(one["memory"]["path"], "/sessions/alpha-app/claude.md")
        self.assertEqual(two["memory"]["path"], "/sessions/beta-app/claude.md")

    # ---- #20 deletion ----

    def test_forget_removes_session_block_and_index_row(self):
        stored = self._store(title="deletable", project="demo")
        memory_id = stored["memory"]["memory_id"]
        result = self.manager.forget(memory_id)
        self.assertEqual(result["status"], "forgotten")
        self.assertNotIn(f"session:{memory_id}", self.manager.read("/sessions/demo/claude.md"))
        self.assertIsNone(self.manager.index.by_id(memory_id))

    def test_forget_keeps_sibling_blocks_and_frontmatter(self):
        first = self._store(title="first", project="demo")
        self._store(title="second", project="demo")
        self.manager.forget(first["memory"]["memory_id"])
        content = self.manager.read("/sessions/demo/claude.md")
        self.assertTrue(content.startswith("---"))
        self.assertIn("type: session", content)
        self.assertIn("## claude-second", content)
        self.assertNotIn("## claude-first", content)

    def test_forget_missing_session_id_reports_not_found(self):
        self.assertEqual(self.manager.forget("nosuchid")["status"], "not_found")

    def test_entry_deletion_still_works(self):
        from memory_hub.models import MemoryCandidate
        stored = self.manager.propose(MemoryCandidate("An ordinary fact.", "topic", "stated",
                                                      "demo", "claude"))
        result = self.manager.forget(stored["memory"]["memory_id"])
        self.assertEqual(result["status"], "forgotten")

    # ---- #24 orphan blocks ----

    def test_audit_reports_session_block_without_id_marker(self):
        self._store(title="orphan", project="demo")
        path = self.manager.vault.resolve("/sessions/demo/claude.md")
        import re
        path.write_text(re.sub(r"<!-- session:[a-z0-9]+ -->", "",
                               path.read_text(encoding="utf-8")), encoding="utf-8")
        self.manager.reindex()
        audit = self.manager.audit()
        self.assertFalse(audit["healthy"])
        self.assertEqual(len(audit["orphan_session_blocks"]), 1)
        self.assertEqual(audit["orphan_session_blocks"][0]["heading"], "claude-orphan-2026-09-06-100000")

    def test_audit_healthy_for_intact_session_file(self):
        self._store(title="intact", project="demo")
        self.assertEqual(self.manager.audit()["orphan_session_blocks"], [])

    # ---- #25 dedup ----

    def test_identical_session_resubmission_is_a_duplicate(self):
        first = self._store(title="retry", project="demo")
        second = self._store(title="retry", project="demo")
        self.assertEqual(first["status"], "stored")
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(self.manager.read("/sessions/demo/claude.md").count("## claude-retry"), 1)

    def test_retry_without_explicit_date_is_still_a_duplicate(self):
        first = self.manager.propose_session({
            "model": "claude", "title": "timeout", "project": "demo",
            "investigated": ["same body"], "learned": [], "completed": [], "next_steps": []})
        second = self.manager.propose_session({
            "model": "claude", "title": "timeout", "project": "demo",
            "investigated": ["same body"], "learned": [], "completed": [], "next_steps": []})
        self.assertEqual(first["status"], "stored")
        self.assertEqual(second["status"], "duplicate")

    def test_distinct_sessions_with_same_title_are_both_stored(self):
        first = self._store(title="daily", investigated=["monday work"], project="demo")
        second = self._store(title="daily", investigated=["tuesday work"], project="demo")
        # Neither is a duplicate: same title, different bodies. The second one's project
        # cross-link may still land in the update band, which is a separate outcome (#22).
        self.assertEqual(first["status"], "stored")
        self.assertIn(second["status"], {"stored", "stored_without_project_link"})
        self.assertEqual(self.manager.read("/sessions/demo/claude.md").count("## claude-daily"), 2)

    # ---- #22 cross-link ----

    def test_dropped_project_cross_link_is_reported(self):
        self._store(title="first", investigated=["Investigated the retry backoff behaviour"],
                    project="demo")
        second = self._store(title="second",
                             investigated=["Investigated the retry backoff behaviour."],
                             project="demo")
        self.assertEqual(second["status"], "stored_without_project_link")
        self.assertIn("project_link_supersedes", second)
        self.assertEqual(self.manager.read("/projects/demo.md").count("Session summary"), 1)

    def test_successful_cross_link_still_reports_stored(self):
        result = self._store(title="linked", project="demo")
        self.assertEqual(result["status"], "stored")
        self.assertEqual(result["project"]["status"], "stored")

    # ---- #19 write mode ----

    def test_review_mode_writes_nothing_to_the_vault(self):
        result = self._store(title="queued-only", project="demo")
        self.assertEqual(result["status"], "stored")
        queued = self.manager.propose_session({
            "model": "claude", "title": "review-only", "date": "2026-09-06T12:00:00",
            "project": "demo", "investigated": ["not yet persisted"], "learned": [],
            "completed": [], "next_steps": []}, write_mode="review")
        self.assertEqual(queued["status"], "queued")
        self.assertNotIn("## claude-review-only", self.manager.read("/sessions/demo/claude.md"))
        self.assertEqual(len(self.manager.list_pending()), 1)

    def test_auto_and_review_modes_differ_on_identical_input(self):
        payload = {"model": "gemini", "title": "modes", "date": "2026-09-06T12:00:00",
                   "project": "demo", "investigated": ["one"], "learned": [],
                   "completed": [], "next_steps": []}
        self.assertEqual(self.manager.propose_session(dict(payload), write_mode="review")["status"],
                         "queued")
        self.assertEqual(self.manager.propose_session(dict(payload), write_mode="auto")["status"],
                         "stored")

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
