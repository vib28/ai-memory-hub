import tempfile
import unittest
from pathlib import Path

from memory_hub.manager import MemoryManager
from memory_hub.models import MemoryCandidate, MemoryRecord

class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.manager = MemoryManager(self.vault)
        template = Path(__file__).resolve().parent.parent / "vault_template"
        self.manager.initialize(template)

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def test_store_search_duplicate_forget(self):
        result = self.manager.propose(MemoryCandidate(
            text="Prefers concise answers first.",
            kind="preference",
            tag="preference",
            subject="response-style",
            writer="chatgpt",
        ))
        self.assertEqual(result["status"], "stored")
        mid = result["memory"]["memory_id"]

        search = self.manager.search("concise answers")
        self.assertTrue(any(r["memory_id"] == mid for r in search))

        dup = self.manager.propose(MemoryCandidate(
            text="Prefers concise answers first.",
            kind="preference",
            tag="preference",
            subject="response-style",
            writer="claude",
        ))
        self.assertEqual(dup["status"], "duplicate")

        forgotten = self.manager.forget(mid)
        self.assertEqual(forgotten["status"], "forgotten")
        self.assertIsNone(self.manager.index.by_id(mid))

    def test_secret_rejected(self):
        key_like_value = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
        result = self.manager.propose(MemoryCandidate(
            text=f"My API key = {key_like_value}",
            kind="profile",
            tag="stated",
            subject="credentials",
            writer="chatgpt",
        ))
        self.assertEqual(result["status"], "rejected")

    def test_codex_writer_is_preserved(self):
        result = self.manager.propose(MemoryCandidate(
            text="Uses Codex for local development work.",
            kind="project",
            tag="stated",
            subject="development-tooling",
            writer="codex",
        ))
        self.assertEqual(result["status"], "stored")
        self.assertEqual(result["memory"]["writer"], "codex")

    def test_qwen_writer_is_preserved(self):
        result = self.manager.propose(MemoryCandidate(
            text="Uses Qwen for local development work.",
            kind="project",
            tag="stated",
            subject="development-tooling",
            writer="qwen",
        ))
        self.assertEqual(result["status"], "stored")
        self.assertEqual(result["memory"]["writer"], "qwen")

    def test_project_identity_routes_aliases_to_one_file(self):
        first = self.manager.propose(MemoryCandidate(
            text="The repository uses a local-first memory pipeline.",
            kind="project", tag="stated", subject="ai-memory-hub",
            writer="codex", entity_id="vib28-ai-memory-hub",
        ))
        second = self.manager.propose(MemoryCandidate(
            text="The repository keeps the Obsidian vault as canonical storage.",
            kind="project", tag="constraint", subject="repository-memory",
            writer="claude", entity_id="vib28-ai-memory-hub",
        ))
        self.assertEqual(first["status"], "stored")
        self.assertEqual(second["status"], "stored")
        self.assertEqual(first["memory"]["path"], second["memory"]["path"])
        content = (self.vault / first["memory"]["path"].lstrip("/")).read_text(encoding="utf-8")
        self.assertIn("id: vib28-ai-memory-hub", content)
        self.assertIn("repository-memory", content)

    def test_project_without_entity_id_does_not_use_prefix_fallback(self):
        first = self.manager.propose(MemoryCandidate(
            text="The canonical project has one subject.",
            kind="project", tag="stated", subject="ai-memory-hub", writer="codex",
        ))
        second = self.manager.propose(MemoryCandidate(
            text="The plan has a related but separate subject.",
            kind="project", tag="stated",
            subject="ai-memory-hub-session-pattern-plan", writer="claude",
        ))
        self.assertEqual(first["status"], "stored")
        self.assertEqual(second["status"], "stored")
        self.assertEqual(first["memory"]["path"], "/projects/ai-memory-hub.md")
        self.assertEqual(
            second["memory"]["path"],
            "/projects/ai-memory-hub-session-pattern-plan.md",
        )
        self.assertNotIn("plan has a related", self.manager.read(first["memory"]["path"]))

    def test_review_queue_preserves_project_entity_id(self):
        candidate = MemoryCandidate(
            text="Review-mode project fact.", kind="project", tag="stated",
            subject="friendly-name", writer="codex", entity_id="stable-project-id",
        )
        queued = self.manager.queue(candidate)
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["proposal"]["entity_id"], "stable-project-id")
        approved = self.manager.approve(queued["proposal"]["proposal_id"])
        self.assertEqual(approved["status"], "stored")
        self.assertEqual(approved["memory"]["path"], "/projects/stable-project-id.md")

    def test_project_audit_reports_exact_duplicates_and_name_splits(self):
        first = self.manager.propose(MemoryCandidate(
            text="Same project fact.", kind="project", tag="stated",
            subject="alpha", writer="codex",
        ))
        self.assertEqual(first["status"], "stored")
        duplicate_path = self.vault / "projects" / "alpha-copy.md"
        duplicate_path.write_text(
            "---\ntype: project\nid: alpha-copy\naliases:\n---\n\n"
            "- [stated] Same project fact. <!-- mem:duplicate-project source:claude subject:alpha-copy date:2026-09-06 -->\n",
            encoding="utf-8",
        )
        report = self.manager.project_audit()
        self.assertFalse(report["healthy"])
        self.assertTrue(report["exact_duplicate_groups"])
        self.assertTrue(report["possible_name_splits"])

    def test_project_link_dry_run_then_reversible_apply(self):
        source = self.manager.propose(MemoryCandidate(
            text="Source project history.", kind="project", tag="stated",
            subject="widget-app-ui", writer="claude", entity_id="widget-app-ui",
        ))["memory"]
        target = self.manager.propose(MemoryCandidate(
            text="Target project history.", kind="project", tag="decided",
            subject="widget-app", writer="codex", entity_id="widget-app",
        ))["memory"]
        preview = self.manager.project_link(source["path"], target["path"])
        self.assertEqual(preview["status"], "preview")
        self.assertEqual(preview["records_to_move"], 1)
        self.assertTrue((self.vault / source["path"].lstrip("/")).exists())

        applied = self.manager.project_link(source["path"], target["path"], apply=True)
        self.assertEqual(applied["status"], "linked")
        self.assertTrue((self.vault / applied["backup"].lstrip("/")).exists())
        self.assertFalse((self.vault / source["path"].lstrip("/")).exists())
        target_text = (self.vault / target["path"].lstrip("/")).read_text(encoding="utf-8")
        self.assertIn("Source project history.", target_text)
        self.assertIn(source["memory_id"], target_text)

    def test_new_entry_timestamp_and_subject_survive_reindex(self):
        first = self.manager.propose(MemoryCandidate(
            text="Uses Windows as the primary development OS.",
            kind="profile",
            tag="stated",
            subject="primary-development-os",
            writer="chatgpt",
        ))
        second = self.manager.propose(MemoryCandidate(
            text="Uses English for technical communication.",
            kind="profile",
            tag="stated",
            subject="technical-language",
            writer="chatgpt",
        ))
        self.assertRegex(first["memory"]["date"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
        self.manager.reindex()
        self.assertEqual(self.manager.index.by_id(first["memory"]["memory_id"])["subject"], "primary-development-os")
        self.assertEqual(self.manager.index.by_id(second["memory"]["memory_id"])["subject"], "technical-language")
        self.assertEqual(self.manager.conflicts(), [])

    def test_edit_normalizes_a_legacy_subject_for_reindex(self):
        memory_id = "legacy-subject"
        path = self.vault / "profile.md"
        path.write_text(
            "---\ntype: profile\n---\n\n"
            "- [stated] Uses Windows. <!-- mem:legacy-subject source:chatgpt date:2026-09-04 -->\n",
            encoding="utf-8",
        )
        self.manager.index.upsert(MemoryRecord(
            memory_id, "/profile.md", "Uses Windows.", "profile", "stated",
            "Primary Development OS", "chatgpt", "2026-09-04",
        ))
        self.assertEqual(self.manager.edit(memory_id, "Uses Windows for development.")["status"], "updated")
        self.manager.reindex()
        self.assertEqual(self.manager.index.by_id(memory_id)["subject"], "primary-development-os")

    def test_supersede(self):
        old = self.manager.propose(MemoryCandidate(
            text="Uses Windows as the primary development OS.",
            kind="profile",
            tag="stated",
            subject="operating-system",
            writer="claude",
        ))
        old_id = old["memory"]["memory_id"]

        new = self.manager.supersede(old_id, MemoryCandidate(
            text="Uses Fedora Linux as the primary development OS.",
            kind="profile",
            tag="stated",
            subject="operating-system",
            writer="chatgpt",
        ))
        self.assertEqual(new["status"], "stored")
        self.assertEqual(self.manager.index.by_id(old_id)["tag"], "superseded")

    def test_reserved_target_path_is_rejected(self):
        for reserved in ("/MEMORY.md", "/AI_INSTRUCTIONS.md", "ai_instructions.md"):
            result = self.manager.propose(MemoryCandidate(
                text="Attempt to plant instructions for all connected tools.",
                kind="topic",
                tag="stated",
                subject="whatever",
                writer="other",
                target_path=reserved,
            ))
            self.assertEqual(result["status"], "rejected", reserved)
            self.assertIn("reserved", result["reason"])

    def test_near_duplicate_update_is_surfaced_not_silently_dropped(self):
        first = self.manager.propose(MemoryCandidate(
            text="Uses Python 3.11 for local development.",
            kind="profile",
            tag="stated",
            subject="python-version",
            writer="chatgpt",
        ))
        self.assertEqual(first["status"], "stored")

        near = self.manager.propose(MemoryCandidate(
            text="Uses Python 3.12 for local development.",
            kind="profile",
            tag="stated",
            subject="python-version",
            writer="chatgpt",
        ))
        self.assertEqual(near["status"], "possible_update")
        self.assertEqual(near["memory"]["memory_id"], first["memory"]["memory_id"])

        applied = self.manager.supersede(near["memory"]["memory_id"], MemoryCandidate(
            text="Uses Python 3.12 for local development.",
            kind="profile",
            tag="stated",
            subject="python-version",
            writer="chatgpt",
        ))
        self.assertEqual(applied["status"], "stored")
        self.assertEqual(self.manager.index.by_id(first["memory"]["memory_id"])["tag"], "superseded")

    def test_exact_duplicate_check_is_scoped_to_kind(self):
        first = self.manager.propose(MemoryCandidate(
            text="Migrated the frontend to TypeScript.",
            kind="topic",
            tag="stated",
            subject="frontend-migration",
            writer="chatgpt",
        ))
        self.assertEqual(first["status"], "stored")

        other_kind = self.manager.propose(MemoryCandidate(
            text="Migrated the frontend to TypeScript.",
            kind="decision",
            tag="decided",
            subject="frontend-migration",
            writer="chatgpt",
        ))
        self.assertEqual(other_kind["status"], "stored")
        self.assertNotEqual(other_kind["memory"]["memory_id"], first["memory"]["memory_id"])

    def test_audit_healthy(self):
        self.manager.propose(MemoryCandidate(
            text="Prefers Python for small automation tools.",
            kind="preference",
            tag="preference",
            subject="coding",
            writer="chatgpt",
        ))
        audit = self.manager.audit()
        self.assertTrue(audit["healthy"], audit)


class SubjectAuditTests(unittest.TestCase):
    """#34: subject_audit() generalizes project_audit()'s exact-hash and
    possible-split detection to every memory kind, read-only."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.manager = MemoryManager(self.vault)
        template = Path(__file__).resolve().parent.parent / "vault_template"
        self.manager.initialize(template)

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def test_empty_vault_is_healthy(self):
        report = self.manager.subject_audit()
        self.assertTrue(report["healthy"], report)
        self.assertEqual(report["exact_duplicate_groups"], [])
        self.assertEqual(report["subject_variant_candidates"], [])
        self.assertEqual(report["possible_file_splits"], [])

    def test_exact_duplicate_detected_for_a_non_project_kind(self):
        """project_audit() only ever looked at kind == "project"; this is the
        generalization the issue asked for, exercised on "preference" instead,
        which shares one file (/preferences.md) across every subject."""
        self.manager.propose(MemoryCandidate(
            text="Prefers concise answers with no filler.", kind="preference",
            tag="preference", subject="response-style", writer="claude",
        ))
        duplicate_path = self.vault / "preferences.md"
        content = duplicate_path.read_text(encoding="utf-8")
        content += (
            "\n- [preference] Prefers concise answers with no filler. "
            "<!-- mem:dup-pref-001 source:codex subject:response-style-alt date:2026-09-06 -->\n"
        )
        duplicate_path.write_text(content, encoding="utf-8")
        report = self.manager.subject_audit()
        self.assertFalse(report["healthy"])
        self.assertTrue(report["exact_duplicate_groups"])
        flat = [row for group in report["exact_duplicate_groups"] for row in group]
        self.assertTrue(all(row["kind"] == "preference" for row in flat))

    def test_duplicates_do_not_cross_kind_boundaries(self):
        """The same text under different kinds is not a duplicate of itself --
        grouping must be keyed on (kind, hash), not hash alone."""
        self.manager.propose(MemoryCandidate(
            text="Ship the release on Friday.", kind="preference",
            tag="preference", subject="release-cadence", writer="claude",
        ))
        self.manager.propose(MemoryCandidate(
            text="Ship the release on Friday.", kind="decision",
            tag="decided", subject="release-plan", writer="codex",
        ))
        report = self.manager.subject_audit()
        self.assertEqual(report["exact_duplicate_groups"], [])

    def test_superseded_records_are_excluded(self):
        first = self.manager.propose(MemoryCandidate(
            text="Uses Windows as the primary development OS.", kind="profile",
            tag="stated", subject="general", writer="claude",
        ))
        duplicate_path = self.vault / "profile.md"
        content = duplicate_path.read_text(encoding="utf-8")
        content += (
            "\n- [stated] Uses Windows as the primary development OS. "
            "<!-- mem:dup-profile-001 source:codex subject:general date:2026-09-06 -->\n"
        )
        duplicate_path.write_text(content, encoding="utf-8")
        self.manager.reindex()
        report = self.manager.subject_audit()
        self.assertTrue(report["exact_duplicate_groups"])
        self.manager.supersede(first["memory"]["memory_id"], MemoryCandidate(
            text="Uses Windows as the primary development OS, confirmed 2026.",
            kind="profile", tag="stated", subject="general", writer="claude",
        ))
        report = self.manager.subject_audit()
        self.assertEqual(report["exact_duplicate_groups"], [])

    def test_subject_variant_candidates_for_a_non_project_file_per_subject_kind(self):
        self.manager.propose(MemoryCandidate(
            text="Widget rendering pipeline overview.", kind="topic",
            tag="stated", subject="widget-app", writer="claude",
        ))
        self.manager.propose(MemoryCandidate(
            text="Widget rendering pipeline, UI layer detail.", kind="topic",
            tag="stated", subject="widget-app-ui", writer="codex",
        ))
        report = self.manager.subject_audit()
        self.assertFalse(report["healthy"])
        self.assertTrue(any(
            c["kind"] == "topic" and set(c["subjects"]) == {"widget-app", "widget-app-ui"}
            for c in report["subject_variant_candidates"]
        ))
        self.assertTrue(any(
            s["kind"] == "topic" and set(Path(p).stem for p in s["paths"]) == {"widget-app", "widget-app-ui"}
            for s in report["possible_file_splits"]
        ))

    def test_preference_variants_are_reported_without_a_file_split(self):
        """preference shares one file (/preferences.md) across all subjects, so
        there is no per-subject file to flag as split -- only the subject-string
        comparison applies."""
        self.manager.propose(MemoryCandidate(
            text="Ask before making destructive changes.", kind="preference",
            tag="preference", subject="git-safety", writer="claude",
        ))
        self.manager.propose(MemoryCandidate(
            text="Confirm before any destructive git operation.", kind="preference",
            tag="preference", subject="git-safety-checks", writer="codex",
        ))
        report = self.manager.subject_audit()
        self.assertTrue(any(
            c["kind"] == "preference" and set(c["subjects"]) == {"git-safety", "git-safety-checks"}
            for c in report["subject_variant_candidates"]
        ))
        self.assertEqual(
            [s for s in report["possible_file_splits"] if s["kind"] == "preference"], [])

    def test_session_subjects_are_never_treated_as_variants(self):
        """Session subjects are per-instance (writer-title-date), not entity names --
        a shared hyphen prefix between two sessions is coincidence, not sprawl."""
        self.manager.propose_session({
            "model": "claude", "title": "widget-app work", "date": "2026-09-01",
            "project": None, "investigated": ["a"], "learned": ["b"],
            "completed": ["c"], "next_steps": ["d"],
        }, write_mode="auto")
        self.manager.propose_session({
            "model": "claude", "title": "widget-app-ui work", "date": "2026-09-02",
            "project": None, "investigated": ["e"], "learned": ["f"],
            "completed": ["g"], "next_steps": ["h"],
        }, write_mode="auto")
        report = self.manager.subject_audit()
        self.assertEqual(
            [c for c in report["subject_variant_candidates"] if c["kind"] == "session"], [])
        self.assertEqual(
            [s for s in report["possible_file_splits"] if s["kind"] == "session"], [])

    def test_kinds_filter_narrows_scope(self):
        self.manager.propose(MemoryCandidate(
            text="Widget topic note.", kind="topic", tag="stated",
            subject="widget-app", writer="claude",
        ))
        self.manager.propose(MemoryCandidate(
            text="Widget topic note, UI layer.", kind="topic", tag="stated",
            subject="widget-app-ui", writer="codex",
        ))
        report = self.manager.subject_audit(kinds=["preference"])
        self.assertTrue(report["healthy"])
        self.assertEqual(report["kinds"], ["preference"])

    def test_audit_never_mutates_the_vault(self):
        self.manager.propose(MemoryCandidate(
            text="Widget topic note.", kind="topic", tag="stated",
            subject="widget-app", writer="claude",
        ))
        self.manager.propose(MemoryCandidate(
            text="Widget topic note, UI layer.", kind="topic", tag="stated",
            subject="widget-app-ui", writer="codex",
        ))
        before = {p: p.read_text(encoding="utf-8") for p in self.vault.rglob("*.md")}
        self.manager.subject_audit()
        self.manager.subject_audit()
        after = {p: p.read_text(encoding="utf-8") for p in self.vault.rglob("*.md")}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
