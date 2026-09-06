import re
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

    def test_context_prime_is_bounded(self):
        self.manager.propose(MemoryCandidate(
            text="The project uses a local-first Markdown vault.",
            kind="project", tag="stated", subject="demo", writer="codex",
        ))
        result = self.manager.context_prime(project="demo", query="local vault", limit=5, max_chars=500)
        self.assertEqual(result["status"], "ok")
        self.assertLessEqual(result["characters"], 500)
        self.assertLessEqual(len(result["memories"]), 5)
        self.assertTrue(all("text" in item and "path" in item for item in result["memories"]))

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


class FileEntityIdentityTests(unittest.TestCase):
    """#35: entity_id/aliases routing, originally project-only (#33), generalized
    to every FILE_PER_ENTITY_KINDS kind (topic, decision, person)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.manager = MemoryManager(self.vault)
        template = Path(__file__).resolve().parent.parent / "vault_template"
        self.manager.initialize(template)

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def test_topic_entity_id_routes_aliases_to_one_file(self):
        first = self.manager.propose(MemoryCandidate(
            text="Widget rendering uses a virtual DOM diff.", kind="topic", tag="stated",
            subject="widget-rendering", writer="codex", entity_id="widget-rendering",
        ))
        second = self.manager.propose(MemoryCandidate(
            text="Widget paint pipeline batches layout passes.", kind="topic", tag="stated",
            subject="paint-pipeline", writer="claude", entity_id="widget-rendering",
        ))
        self.assertEqual(first["status"], "stored")
        self.assertEqual(second["status"], "stored")
        self.assertEqual(first["memory"]["path"], second["memory"]["path"])
        content = (self.vault / first["memory"]["path"].lstrip("/")).read_text(encoding="utf-8")
        self.assertIn("id: widget-rendering", content)
        self.assertIn("paint-pipeline", content)

    def test_decision_and_person_get_the_same_treatment(self):
        for kind, directory in (("decision", "decisions"), ("person", "people")):
            first = self.manager.propose(MemoryCandidate(
                text=f"First {kind} fact.", kind=kind, tag="decided" if kind == "decision" else "stated",
                subject="alpha", writer="codex", entity_id="shared-entity",
            ))
            second = self.manager.propose(MemoryCandidate(
                text=f"Second {kind} fact.", kind=kind, tag="decided" if kind == "decision" else "stated",
                subject="beta", writer="claude", entity_id="shared-entity",
            ))
            self.assertEqual(first["memory"]["path"], second["memory"]["path"], kind)
            self.assertEqual(first["memory"]["path"], f"/{directory}/shared-entity.md", kind)

    def test_missing_entity_id_does_not_merge_similar_topic_names(self):
        """#37's fix (no legacy prefix fallback) applies to every generalized
        kind, not just project: two topic writes with no entity_id and
        similar-looking subjects must stay in separate files."""
        first = self.manager.propose(MemoryCandidate(
            text="Widget app overview.", kind="topic", tag="stated",
            subject="widget-app", writer="claude",
        ))
        second = self.manager.propose(MemoryCandidate(
            text="Widget app UI layer detail.", kind="topic", tag="stated",
            subject="widget-app-ui", writer="codex",
        ))
        self.assertNotEqual(first["memory"]["path"], second["memory"]["path"])

    def test_project_link_now_works_for_topic_files(self):
        source = self.manager.propose(MemoryCandidate(
            text="Source topic history.", kind="topic", tag="stated",
            subject="widget-app-ui", writer="claude", entity_id="widget-app-ui",
        ))["memory"]
        target = self.manager.propose(MemoryCandidate(
            text="Target topic history.", kind="topic", tag="stated",
            subject="widget-app", writer="codex", entity_id="widget-app",
        ))["memory"]
        applied = self.manager.project_link(source["path"], target["path"], apply=True)
        self.assertEqual(applied["status"], "linked")
        self.assertFalse((self.vault / source["path"].lstrip("/")).exists())
        target_text = (self.vault / target["path"].lstrip("/")).read_text(encoding="utf-8")
        self.assertIn("Source topic history.", target_text)

    def test_project_link_rejects_mismatched_kinds(self):
        project = self.manager.propose(MemoryCandidate(
            text="A project fact.", kind="project", tag="stated",
            subject="widget-app", writer="claude", entity_id="widget-app",
        ))["memory"]
        topic = self.manager.propose(MemoryCandidate(
            text="A topic fact.", kind="topic", tag="stated",
            subject="widget-topic", writer="claude", entity_id="widget-topic",
        ))["memory"]
        result = self.manager.project_link(topic["path"], project["path"])
        self.assertEqual(result["status"], "rejected")

    def test_subject_audit_reports_alias_collision_for_topics(self):
        self.manager.propose(MemoryCandidate(
            text="Widget topic fact.", kind="topic", tag="stated",
            subject="widget-app", writer="claude", entity_id="widget-app",
        ))
        colliding_path = self.vault / "topics" / "widget-app-copy.md"
        colliding_path.write_text(
            "---\ntype: topic\nid: widget-app\naliases:\n---\n\n"
            "- [stated] Duplicate identity claim. "
            "<!-- mem:collide-001 source:codex subject:widget-app-copy date:2026-09-06 -->\n",
            encoding="utf-8",
        )
        report = self.manager.subject_audit(kinds=["topic"])
        self.assertFalse(report["healthy"])
        self.assertTrue(any(c["kind"] == "topic" and c["alias"] == "widget-app"
                            for c in report["alias_collisions"]))


class EntityAliasLinkTests(unittest.TestCase):
    """#35: shared-file kinds (preference, profile) get identity through a
    small registry file instead of per-file frontmatter, since all their
    subjects already live in one shared Markdown file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.manager = MemoryManager(self.vault)
        template = Path(__file__).resolve().parent.parent / "vault_template"
        self.manager.initialize(template)

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def test_rejects_a_file_per_subject_kind(self):
        result = self.manager.entity_alias_link("project", "a", "b")
        self.assertEqual(result["status"], "rejected")

    def test_rejects_identical_subjects(self):
        result = self.manager.entity_alias_link("preference", "git-safety", "git-safety")
        self.assertEqual(result["status"], "rejected")

    def test_preview_does_not_write_the_registry(self):
        # The registry file itself already exists (vault_template seeds it with
        # its own documentation), so the thing to prove is that its *content* is
        # untouched by a preview, not that the file is absent.
        registry_path = self.vault / "entity-aliases.md"
        before = registry_path.read_text(encoding="utf-8")
        preview = self.manager.entity_alias_link("preference", "git-safety-checks", "git-safety")
        self.assertEqual(preview["status"], "preview")
        self.assertEqual(preview["entity_id"], "git-safety")
        self.assertIn("git-safety-checks", preview["aliases"])
        self.assertEqual(registry_path.read_text(encoding="utf-8"), before)

    def test_apply_persists_and_a_second_call_extends_the_same_entity(self):
        self.manager.propose(MemoryCandidate(
            text="Ask before making destructive changes.", kind="preference",
            tag="preference", subject="git-safety", writer="claude",
        ))
        self.manager.propose(MemoryCandidate(
            text="Confirm before any destructive git operation.", kind="preference",
            tag="preference", subject="git-safety-checks", writer="codex",
        ))
        first = self.manager.entity_alias_link("preference", "git-safety-checks", "git-safety", apply=True)
        self.assertEqual(first["status"], "linked")
        registry_path = self.vault / "entity-aliases.md"
        self.assertTrue(registry_path.exists())
        content = registry_path.read_text(encoding="utf-8")
        self.assertIn("## preference: git-safety", content)
        self.assertIn("- git-safety-checks", content)

        # Linking a third subject to either side of the pair joins the same
        # entity rather than forking a second registry entry for it.
        second = self.manager.entity_alias_link("preference", "confirm-destructive-ops", "git-safety-checks", apply=True)
        self.assertEqual(second["status"], "linked")
        self.assertEqual(second["entity_id"], "git-safety")
        content = registry_path.read_text(encoding="utf-8")
        # A plain substring count would also match the template's own indented
        # documentation example; count real (column-0) headings only, the same
        # way load_entity_aliases anchors on ^## with re.M.
        real_headings = re.findall(r"(?m)^## preference: git-safety\s*$", content)
        self.assertEqual(len(real_headings), 1)
        self.assertIn("- confirm-destructive-ops", content)

    def test_original_entries_are_untouched_by_linking(self):
        first = self.manager.propose(MemoryCandidate(
            text="Ask before making destructive changes.", kind="preference",
            tag="preference", subject="git-safety", writer="claude",
        ))["memory"]
        second = self.manager.propose(MemoryCandidate(
            text="Confirm before any destructive git operation.", kind="preference",
            tag="preference", subject="git-safety-checks", writer="codex",
        ))["memory"]
        preferences_path = self.vault / "preferences.md"
        before = preferences_path.read_text(encoding="utf-8")
        self.manager.entity_alias_link("preference", "git-safety-checks", "git-safety", apply=True)
        after = preferences_path.read_text(encoding="utf-8")
        self.assertEqual(before, after)
        self.assertIsNotNone(self.manager.index.by_id(first["memory_id"]))
        self.assertIsNotNone(self.manager.index.by_id(second["memory_id"]))

    def test_linked_pair_moves_from_candidates_to_linked_entities_in_the_audit(self):
        self.manager.propose(MemoryCandidate(
            text="Ask before making destructive changes.", kind="preference",
            tag="preference", subject="git-safety", writer="claude",
        ))
        self.manager.propose(MemoryCandidate(
            text="Confirm before any destructive git operation.", kind="preference",
            tag="preference", subject="git-safety-checks", writer="codex",
        ))
        before = self.manager.subject_audit(kinds=["preference"])
        self.assertTrue(any(
            c["kind"] == "preference" and set(c["subjects"]) == {"git-safety", "git-safety-checks"}
            for c in before["subject_variant_candidates"]
        ))
        self.assertEqual(before["linked_entities"], [])

        self.manager.entity_alias_link("preference", "git-safety-checks", "git-safety", apply=True)
        after = self.manager.subject_audit(kinds=["preference"])
        self.assertFalse(any(
            set(c["subjects"]) == {"git-safety", "git-safety-checks"}
            for c in after["subject_variant_candidates"]
        ))
        self.assertTrue(any(
            set(link["subjects"]) == {"git-safety", "git-safety-checks"} and link["entity_id"] == "git-safety"
            for link in after["linked_entities"]
        ))

    def test_linked_preferences_are_grouped_by_conflicts_and_resolvable(self):
        """A linked pair with genuinely different text is not itself a conflict
        (conflicts() requires >1 distinct text under the group) -- so first prove
        grouping via resolve_conflict() collapsing both onto one kept entry."""
        first = self.manager.propose(MemoryCandidate(
            text="Ask before making destructive changes.", kind="preference",
            tag="preference", subject="git-safety", writer="claude",
        ))["memory"]
        second = self.manager.propose(MemoryCandidate(
            text="Confirm before any destructive git operation.", kind="preference",
            tag="preference", subject="git-safety-checks", writer="codex",
        ))["memory"]
        self.manager.entity_alias_link("preference", "git-safety-checks", "git-safety", apply=True)
        result = self.manager.resolve_conflict(first["memory_id"])
        self.assertEqual(result["status"], "resolved")
        self.assertIn(second["memory_id"], result["superseded"])


if __name__ == "__main__":
    unittest.main()
