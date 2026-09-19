import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        assert result["status"] == "stored"
        mid = result["memory"]["memory_id"]

        search = self.manager.search("concise answers")
        assert any(r["memory_id"] == mid for r in search)

        dup = self.manager.propose(MemoryCandidate(
            text="Prefers concise answers first.",
            kind="preference",
            tag="preference",
            subject="response-style",
            writer="claude",
        ))
        assert dup["status"] == "duplicate"

        forgotten = self.manager.forget(mid)
        assert forgotten["status"] == "forgotten"
        assert self.manager.index.by_id(mid) is None

    def test_memory_index_descriptions_derive_from_file_content(self):
        first = self.manager.propose(MemoryCandidate(
            text="The project uses local Markdown as its canonical source.",
            kind="project", tag="stated", subject="demo", writer="codex",
        ))
        first_id = first["memory"]["memory_id"]
        row = next(line for line in self.manager.read("/MEMORY.md").splitlines()
                   if "[[projects/demo]]" in line)
        assert "Project notes: The project uses local Markdown" in row
        assert "Project memory for demo" not in row

        second = self.manager.propose(MemoryCandidate(
            text="The worker retries bounded batches after a transient failure.",
            kind="project", tag="constraint", subject="demo", writer="codex",
        ))
        assert first_id != second["memory"]["memory_id"]
        row = next(line for line in self.manager.read("/MEMORY.md").splitlines()
                   if "[[projects/demo]]" in line)
        assert "local Markdown" in row
        assert "retries bounded batches" in row

        self.manager.propose(MemoryCandidate(
            text="Latest active finding " + ("detail " * 60),
            kind="project", tag="stated", subject="demo", writer="codex",
        ))
        row = next(line for line in self.manager.read("/MEMORY.md").splitlines()
                   if "[[projects/demo]]" in line)
        assert "Latest active finding" in row

        self.manager.edit(first_id, "The project now uses a local SQLite index.")
        row = next(line for line in self.manager.read("/MEMORY.md").splitlines()
                   if "[[projects/demo]]" in line)
        assert "local SQLite index" in row
        assert "canonical source" not in row

    def test_profile_and_preference_index_descriptions_remain_fixed(self):
        self.manager.propose(MemoryCandidate(
            text="Uses Windows for development.", kind="profile", tag="stated",
            subject="primary-os", writer="codex",
        ))
        self.manager.propose(MemoryCandidate(
            text="Prefer concise technical explanations.", kind="preference", tag="preference",
            subject="response-style", writer="codex",
        ))
        index = self.manager.read("/MEMORY.md")
        assert "Stable identity, role, stack, timezone, and long-term context" in index
        assert "Communication, workflow, research, and output preferences" in index

    def test_context_prime_is_bounded(self):
        self.manager.propose(MemoryCandidate(
            text="The project uses a local-first Markdown vault.",
            kind="project", tag="stated", subject="demo", writer="codex",
        ))
        result = self.manager.context_prime(project="demo", query="local vault", limit=5, max_chars=500)
        assert result["status"] == "ok"
        assert result["characters"] <= 500
        assert result["budget_type"] == "serialized-json-characters"
        packet = json.dumps({"memories": result["memories"]}, ensure_ascii=False, separators=(",", ":"))
        assert len(packet) <= 500
        assert len(result["memories"]) <= 5
        assert all("text" in item and "path" in item for item in result["memories"])

    def test_context_prime_filters_project_and_oversized_first_result(self):
        rows = [
            {"memory_id": "other", "path": "/projects/alpha.md", "kind": "project",
             "subject": "other", "text": "x" * 2000, "tag": "stated"},
            {"memory_id": "alpha", "path": "/projects/alpha.md", "kind": "project",
             "subject": "alpha", "text": "alpha", "tag": "stated"},
        ]
        with patch.object(self.manager.index, "search", return_value=rows):
            result = self.manager.context_prime(project="alpha", max_chars=500)
        assert result["characters"] <= 500
        assert result["memories"] == []
        assert result["truncation_reason"] == "context budget reached"

    def test_context_prime_scope_filters_before_ranking_and_labels_global(self):
        self.manager.propose(MemoryCandidate(
            text="Shared continuity signal for the alpha handoff.",
            kind="project", tag="stated", subject="alpha", writer="codex",
        ))
        self.manager.propose(MemoryCandidate(
            text="Shared continuity signal for the beta handoff.",
            kind="project", tag="stated", subject="beta", writer="codex",
        ))
        self.manager.propose(MemoryCandidate(
            text="Shared continuity preference for handoff packets.",
            kind="preference", tag="preference", subject="handoff-style", writer="codex",
        ))
        result = self.manager.context_prime(project="alpha", query="shared continuity signal", limit=10)
        paths = {item["path"] for item in result["memories"]}
        assert "/projects/alpha.md" in paths
        assert "/projects/beta.md" not in paths
        assert "global" in {item["scope"] for item in result["memories"]}
        assert all(item["scope"] != "unscoped" for item in result["memories"])

    def test_context_prime_excludes_superseded_and_reports_empty_honestly(self):
        old = self.manager.propose(MemoryCandidate(
            text="Retired alpha continuity instruction.",
            kind="project", tag="stated", subject="alpha", writer="codex",
        ))
        assert old["status"] == "stored"
        replacement = self.manager.supersede(old["memory"]["memory_id"], MemoryCandidate(
            text="Current alpha continuity instruction.",
            kind="project", tag="stated", subject="alpha", writer="codex",
        ))
        assert replacement["status"] == "stored"
        result = self.manager.context_prime(project="missing-project", query="no such continuity")
        assert result["memories"] == []
        assert result["candidate_count"] == 0
        assert not result["truncated"]
        assert result["truncation_reason"] is None

    def test_context_prime_puts_latest_project_session_first(self):
        older = self.manager.propose_session({
            "model": "codex", "title": "old", "date": "2026-09-07T10:00:00",
            "project": "alpha", "investigated": ["old task"], "learned": [],
            "completed": [], "next_steps": ["old next step"],
        })
        newer = self.manager.propose_session({
            "model": "codex", "title": "new", "date": "2026-09-08T10:00:00",
            "project": "alpha", "investigated": ["new task"], "learned": [],
            "completed": [], "next_steps": ["new next step"],
        })
        assert older["status"] == "stored"
        assert newer["status"] in {"stored", "stored_without_project_link"}
        result = self.manager.context_prime(project="alpha", query="unlikely", limit=1,
                                            max_chars=12000)
        assert result["memories"][0]["memory_id"] == newer["memory"]["memory_id"]

    def test_secret_rejected(self):
        key_like_value = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
        result = self.manager.propose(MemoryCandidate(
            text=f"My API key = {key_like_value}",
            kind="profile",
            tag="stated",
            subject="credentials",
            writer="chatgpt",
        ))
        assert result["status"] == "rejected"

    def test_codex_writer_is_preserved(self):
        result = self.manager.propose(MemoryCandidate(
            text="Uses Codex for local development work.",
            kind="project",
            tag="stated",
            subject="development-tooling",
            writer="codex",
        ))
        assert result["status"] == "stored"
        assert result["memory"]["writer"] == "codex"

    def test_qwen_writer_is_preserved(self):
        result = self.manager.propose(MemoryCandidate(
            text="Uses Qwen for local development work.",
            kind="project",
            tag="stated",
            subject="development-tooling",
            writer="qwen",
        ))
        assert result["status"] == "stored"
        assert result["memory"]["writer"] == "qwen"

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
        assert first["status"] == "stored"
        assert second["status"] == "stored"
        assert first["memory"]["path"] == second["memory"]["path"]
        content = (self.vault / first["memory"]["path"].lstrip("/")).read_text(encoding="utf-8")
        assert "id: vib28-ai-memory-hub" in content
        assert "repository-memory" in content

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
        assert first["status"] == "stored"
        assert second["status"] == "stored"
        assert first["memory"]["path"] == "/projects/ai-memory-hub.md"
        assert second["memory"]["path"] == "/projects/ai-memory-hub-session-pattern-plan.md"
        assert "plan has a related" not in self.manager.read(first["memory"]["path"])

    def test_review_queue_preserves_project_entity_id(self):
        candidate = MemoryCandidate(
            text="Review-mode project fact.", kind="project", tag="stated",
            subject="friendly-name", writer="codex", entity_id="stable-project-id",
        )
        queued = self.manager.queue(candidate)
        assert queued["status"] == "queued"
        assert queued["proposal"]["entity_id"] == "stable-project-id"
        approved = self.manager.approve(queued["proposal"]["proposal_id"])
        assert approved["status"] == "stored"
        assert approved["memory"]["path"] == "/projects/stable-project-id.md"

    def test_project_audit_reports_exact_duplicates_and_name_splits(self):
        first = self.manager.propose(MemoryCandidate(
            text="Same project fact.", kind="project", tag="stated",
            subject="alpha", writer="codex",
        ))
        assert first["status"] == "stored"
        duplicate_path = self.vault / "projects" / "alpha-copy.md"
        duplicate_path.write_text(
            "---\ntype: project\nid: alpha-copy\naliases:\n---\n\n"
            "- [stated] Same project fact. <!-- mem:duplicate-project source:claude subject:alpha-copy date:2026-09-06 -->\n",
            encoding="utf-8",
        )
        report = self.manager.project_audit()
        assert not report["healthy"]
        assert report["exact_duplicate_groups"]
        assert report["possible_name_splits"]

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
        assert preview["status"] == "preview"
        assert preview["records_to_move"] == 1
        assert (self.vault / source["path"].lstrip("/")).exists()

        applied = self.manager.project_link(source["path"], target["path"], apply=True)
        assert applied["status"] == "linked"
        assert (self.vault / applied["backup"].lstrip("/")).exists()
        assert not (self.vault / source["path"].lstrip("/")).exists()
        target_text = (self.vault / target["path"].lstrip("/")).read_text(encoding="utf-8")
        assert "Source project history." in target_text
        assert source["memory_id"] in target_text

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
        assert re.search(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", first["memory"]["date"])
        self.manager.reindex()
        assert self.manager.index.by_id(first["memory"]["memory_id"])["subject"] == "primary-development-os"
        assert self.manager.index.by_id(second["memory"]["memory_id"])["subject"] == "technical-language"
        assert self.manager.conflicts() == []

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
        assert self.manager.edit(memory_id, "Uses Windows for development.")["status"] == "updated"
        self.manager.reindex()
        assert self.manager.index.by_id(memory_id)["subject"] == "primary-development-os"

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
        assert new["status"] == "stored"
        assert self.manager.index.by_id(old_id)["tag"] == "superseded"

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
            assert result["status"] == "rejected", reserved
            assert "reserved" in result["reason"]

    def test_near_duplicate_update_is_surfaced_not_silently_dropped(self):
        first = self.manager.propose(MemoryCandidate(
            text="Uses Python 3.11 for local development.",
            kind="profile",
            tag="stated",
            subject="python-version",
            writer="chatgpt",
        ))
        assert first["status"] == "stored"

        near = self.manager.propose(MemoryCandidate(
            text="Uses Python 3.12 for local development.",
            kind="profile",
            tag="stated",
            subject="python-version",
            writer="chatgpt",
        ))
        assert near["status"] == "possible_update"
        assert near["memory"]["memory_id"] == first["memory"]["memory_id"]

        applied = self.manager.supersede(near["memory"]["memory_id"], MemoryCandidate(
            text="Uses Python 3.12 for local development.",
            kind="profile",
            tag="stated",
            subject="python-version",
            writer="chatgpt",
        ))
        assert applied["status"] == "stored"
        assert self.manager.index.by_id(first["memory"]["memory_id"])["tag"] == "superseded"

    def test_exact_duplicate_check_is_scoped_to_kind(self):
        first = self.manager.propose(MemoryCandidate(
            text="Migrated the frontend to TypeScript.",
            kind="topic",
            tag="stated",
            subject="frontend-migration",
            writer="chatgpt",
        ))
        assert first["status"] == "stored"

        other_kind = self.manager.propose(MemoryCandidate(
            text="Migrated the frontend to TypeScript.",
            kind="decision",
            tag="decided",
            subject="frontend-migration",
            writer="chatgpt",
        ))
        assert other_kind["status"] == "stored"
        assert other_kind["memory"]["memory_id"] != first["memory"]["memory_id"]

    def test_audit_healthy(self):
        self.manager.propose(MemoryCandidate(
            text="Prefers Python for small automation tools.",
            kind="preference",
            tag="preference",
            subject="coding",
            writer="chatgpt",
        ))
        audit = self.manager.audit()
        assert audit["healthy"], audit


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
        assert report["healthy"], report
        assert report["exact_duplicate_groups"] == []
        assert report["subject_variant_candidates"] == []
        assert report["lexical_candidates"] == []
        assert report["possible_file_splits"] == []

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
        assert not report["healthy"]
        assert report["exact_duplicate_groups"]
        flat = [row for group in report["exact_duplicate_groups"] for row in group]
        assert all(row["kind"] == "preference" for row in flat)

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
        assert report["exact_duplicate_groups"] == []

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
        assert report["exact_duplicate_groups"]
        self.manager.supersede(first["memory"]["memory_id"], MemoryCandidate(
            text="Uses Windows as the primary development OS, confirmed 2026.",
            kind="profile", tag="stated", subject="general", writer="claude",
        ))
        report = self.manager.subject_audit()
        assert report["exact_duplicate_groups"] == []

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
        assert not report["healthy"]
        assert any(c["kind"] == "topic" and set(c["subjects"]) == {"widget-app", "widget-app-ui"} for c in report["subject_variant_candidates"])
        assert any(s["kind"] == "topic" and set(Path(p).stem for p in s["paths"]) == {"widget-app", "widget-app-ui"} for s in report["possible_file_splits"])

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
        assert any(c["kind"] == "preference" and set(c["subjects"]) == {"git-safety", "git-safety-checks"} for c in report["subject_variant_candidates"])
        assert [s for s in report["possible_file_splits"] if s["kind"] == "preference"] == []

    def test_lexical_audit_finds_non_prefix_related_preferences_without_false_positive(self):
        related = [
            ("ai-memory-bug-workflow", "For AI Memory Hub bug fixes, create a GitHub issue with reproduction steps, acceptance criteria, implementation details, verification results, and a regression test. Commonvault. This workflow covers implementation safeguards."),
            ("ai-memory-change-documentation", "For AI Memory Hub documentation changes, document the GitHub issue with reproduction steps, acceptance criteria, implementation details, verification results, and clear rationale. Commonvault. This change record explains reader communication."),
            ("ai-memory-github-documentation", "For AI Memory Hub GitHub work, record reproduction steps, acceptance criteria, implementation details, verification results, and the final implementation comment. Commonvault. This audit case names a reviewable maintenance outcome."),
        ]
        for subject, text in related:
            self.manager.propose(MemoryCandidate(
                text=text, kind="preference", tag="preference", subject=subject, writer="codex",
            ))
        unrelated = [
            ("dashboard-theme", "Prefer dark mode in the dashboard for accessibility. Commonvault. This interface choice concerns visual comfort."),
            ("index-storage", "Use SQLite WAL mode for crash-safe indexing. Commonvault. This storage rule concerns recovery behavior."),
        ]
        for subject, text in unrelated:
            self.manager.propose(MemoryCandidate(
                text=text, kind="preference", tag="preference", subject=subject, writer="codex",
            ))

        report = self.manager.subject_audit(kinds=["preference"])
        pairs = {
            frozenset(candidate["subjects"])
            for candidate in report["lexical_candidates"]
        }
        assert pairs == {frozenset({related[0][0], related[1][0]}), frozenset({related[0][0], related[2][0]}), frozenset({related[1][0], related[2][0]})}
        assert all(candidate["token_overlap"] >= self.manager._LEXICAL_AUDIT_MIN_SHARED_TOKENS and candidate["similarity"] >= self.manager._LEXICAL_AUDIT_DICE_THRESHOLD for candidate in report["lexical_candidates"])
        assert all("commonvault" not in candidate["shared_tokens"] for candidate in report["lexical_candidates"])
        assert report["lexical_candidates"]
        assert not report["healthy"]

    def test_lexical_audit_does_not_reclassify_cumulative_project_logs(self):
        self.manager.propose(MemoryCandidate(
            text="The project keeps Markdown as the canonical source and records the migration decision.",
            kind="project", tag="stated", subject="shared-project", writer="codex",
        ))
        self.manager.propose(MemoryCandidate(
            text="The project keeps Markdown as the canonical source and records the retrieval decision.",
            kind="project", tag="stated", subject="shared-project", writer="codex",
        ))

        report = self.manager.subject_audit(kinds=["project"])
        assert report["lexical_candidates"] == []
        assert report["healthy"]

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
        assert [c for c in report["subject_variant_candidates"] if c["kind"] == "session"] == []
        assert [s for s in report["possible_file_splits"] if s["kind"] == "session"] == []

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
        assert report["healthy"]
        assert report["kinds"] == ["preference"]

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
        assert before == after


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
        assert first["status"] == "stored"
        assert second["status"] == "stored"
        assert first["memory"]["path"] == second["memory"]["path"]
        content = (self.vault / first["memory"]["path"].lstrip("/")).read_text(encoding="utf-8")
        assert "id: widget-rendering" in content
        assert "paint-pipeline" in content

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
            assert first["memory"]["path"] == second["memory"]["path"], kind
            assert first["memory"]["path"] == f"/{directory}/shared-entity.md", kind

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
        assert first["memory"]["path"] != second["memory"]["path"]

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
        assert applied["status"] == "linked"
        assert not (self.vault / source["path"].lstrip("/")).exists()
        target_text = (self.vault / target["path"].lstrip("/")).read_text(encoding="utf-8")
        assert "Source topic history." in target_text

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
        assert result["status"] == "rejected"

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
        assert not report["healthy"]
        assert any(c["kind"] == "topic" and c["alias"] == "widget-app" for c in report["alias_collisions"])


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
        assert result["status"] == "rejected"

    def test_rejects_identical_subjects(self):
        result = self.manager.entity_alias_link("preference", "git-safety", "git-safety")
        assert result["status"] == "rejected"

    def test_preview_does_not_write_the_registry(self):
        # The registry file itself already exists (vault_template seeds it with
        # its own documentation), so the thing to prove is that its *content* is
        # untouched by a preview, not that the file is absent.
        registry_path = self.vault / "entity-aliases.md"
        before = registry_path.read_text(encoding="utf-8")
        preview = self.manager.entity_alias_link("preference", "git-safety-checks", "git-safety")
        assert preview["status"] == "preview"
        assert preview["entity_id"] == "git-safety"
        assert "git-safety-checks" in preview["aliases"]
        assert registry_path.read_text(encoding="utf-8") == before

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
        assert first["status"] == "linked"
        registry_path = self.vault / "entity-aliases.md"
        assert registry_path.exists()
        content = registry_path.read_text(encoding="utf-8")
        assert "## preference: git-safety" in content
        assert "- git-safety-checks" in content

        # Linking a third subject to either side of the pair joins the same
        # entity rather than forking a second registry entry for it.
        second = self.manager.entity_alias_link("preference", "confirm-destructive-ops", "git-safety-checks", apply=True)
        assert second["status"] == "linked"
        assert second["entity_id"] == "git-safety"
        content = registry_path.read_text(encoding="utf-8")
        # A plain substring count would also match the template's own indented
        # documentation example; count real (column-0) headings only, the same
        # way load_entity_aliases anchors on ^## with re.M.
        real_headings = re.findall(r"(?m)^## preference: git-safety\s*$", content)
        assert len(real_headings) == 1
        assert "- confirm-destructive-ops" in content

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
        assert before == after
        assert self.manager.index.by_id(first["memory_id"]) is not None
        assert self.manager.index.by_id(second["memory_id"]) is not None

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
        assert any(c["kind"] == "preference" and set(c["subjects"]) == {"git-safety", "git-safety-checks"} for c in before["subject_variant_candidates"])
        assert before["linked_entities"] == []

        self.manager.entity_alias_link("preference", "git-safety-checks", "git-safety", apply=True)
        after = self.manager.subject_audit(kinds=["preference"])
        assert not any(set(c["subjects"]) == {"git-safety", "git-safety-checks"} for c in after["subject_variant_candidates"])
        assert any(set(link["subjects"]) == {"git-safety", "git-safety-checks"} and link["entity_id"] == "git-safety" for link in after["linked_entities"])

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
        assert result["status"] == "resolved"
        assert second["memory_id"] in result["superseded"]


if __name__ == "__main__":
    unittest.main()
