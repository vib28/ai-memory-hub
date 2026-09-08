from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from memory_hub.github_export import ExportError, ExportOutbox, GitHubPublisher, build_export_payloads, configure, run_once
from memory_hub.manager import MemoryManager


class FakeGitHub:
    def __init__(self, *, fail_after_comment=False):
        self.repo = "owner/repo"
        self.issue = None
        self.comments = []
        self.next_comment_id = 1
        self.fail_after_comment = fail_after_comment
        self.failed_once = False

    def repo_visibility(self):
        return "private"

    def find_issue(self, marker):
        return self.issue if self.issue and marker in self.issue.get("body", "") else None

    def create_issue(self, title, body):
        self.issue = {"number": 42, "html_url": "https://github.com/owner/repo/issues/42", "title": title, "body": body}
        return self.issue

    def update_issue(self, number, body):
        self.issue["body"] = body

    def list_comments(self, number):
        return list(self.comments)

    def create_comment(self, number, body):
        record = {
            "id": self.next_comment_id,
            "html_url": f"https://github.com/owner/repo/issues/42#issuecomment-{self.next_comment_id}",
            "body": body,
        }
        self.next_comment_id += 1
        self.comments.append(record)
        if self.fail_after_comment and not self.failed_once:
            self.failed_once = True
            raise ExportError("simulated timeout after GitHub accepted comment")
        return record

    def update_comment(self, comment_id, body):
        for comment in self.comments:
            if comment["id"] == comment_id:
                comment["body"] = body


class OfflineGitHub(FakeGitHub):
    def repo_visibility(self):
        raise ExportError("simulated offline")


class GitHubExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.manager = MemoryManager(self.vault)
        self.manager.initialize(Path(__file__).resolve().parent.parent / "vault_template")
        self.env = patch.dict("os.environ", {
            "MEMORY_GITHUB_EXPORT_CONFIG": str(self.root / "config.json"),
            "MEMORY_GITHUB_OUTBOX": str(self.root / "outbox.sqlite3"),
            "MEMORY_GITHUB_HEALTH": str(self.root / "health.json"),
        }, clear=False)
        self.env.start()
        configure(self.vault, repo="owner/repo", visibility="private", enabled=True)

    def tearDown(self):
        self.env.stop()
        self.manager.close()
        self.tmp.cleanup()

    def _store(self, sequence, entry_type="checkpoint", learned=None, changed_files=None):
        result = self.manager.propose_session({
            "model": "codex", "title": f"Checkpoint {sequence}", "date": f"2026-09-09T10:00:0{sequence}",
            "project": "export-demo", "investigated": ["Reviewed accepted work"],
            "learned": learned or ["Keep the local vault canonical"],
            "completed": ["Verified the local write"], "next_steps": ["Continue the task"],
            "session_group_id": "export-group", "checkpoint_id": f"batch-{sequence}",
            "sequence": sequence, "entry_type": entry_type, "source_client": "codex",
            "changed_files": changed_files or [f"src/file-{sequence}.py"],
        })
        self.assertEqual(result["status"], "stored")

    def test_sanitized_three_batches_and_final_publish_with_links_and_no_duplicates(self):
        for sequence in (1, 2, 3):
            self._store(sequence)
        self._store(4, entry_type="final")
        fake = FakeGitHub()
        outbox = ExportOutbox(self.root / "outbox.sqlite3")
        publisher = GitHubPublisher(self.vault, client=fake, outbox=outbox)
        try:
            self.assertEqual(publisher.enqueue_accepted()["enqueued"], 4)
            result = publisher.publish_once()
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(fake.comments), 4)
            self.assertIn("### Investigated", fake.comments[0]["body"])
            self.assertIn("### Learned", fake.comments[0]["body"])
            self.assertIn("### Completed", fake.comments[0]["body"])
            self.assertIn("### Next Steps", fake.comments[0]["body"])
            self.assertIn("issuecomment", fake.comments[1]["body"])
            self.assertIn("issuecomment", fake.comments[0]["body"])
            user_comment = {"id": 99, "html_url": "https://github.com/owner/repo/issues/42#issuecomment-99", "body": "User note"}
            fake.comments.append(user_comment)
            fake.issue["body"] += "\n\nUser-maintained context.\n"
            self._store(5)
            publisher.enqueue_accepted()
            publisher.publish_once()
            self.assertIn("User-maintained context.", fake.issue["body"])
            self.assertIn(user_comment, fake.comments)
            self.assertEqual(len([item for item in fake.comments if "ai-memory-hub:checkpoint" in item["body"]]), 5)
            self.assertEqual(publisher.enqueue_accepted()["enqueued"], 5)
        finally:
            publisher.close()
            outbox.close()

    def test_timeout_after_accepted_comment_is_reconciled_by_marker(self):
        self._store(1)
        fake = FakeGitHub(fail_after_comment=True)
        outbox = ExportOutbox(self.root / "outbox.sqlite3")
        publisher = GitHubPublisher(self.vault, client=fake, outbox=outbox)
        try:
            publisher.enqueue_accepted()
            first = publisher.publish_once()
            self.assertEqual(first["status"], "degraded")
            outbox.conn.execute("UPDATE exports SET next_attempt_at='2000-01-01T00:00:00+00:00'")
            outbox.conn.commit()
            second = publisher.publish_once()
            self.assertEqual(second["status"], "ok")
            self.assertEqual(len(fake.comments), 1)
        finally:
            publisher.close()
            outbox.close()

    def test_offline_destination_keeps_local_outbox_and_never_blocks_local_write(self):
        self._store(1)
        fake = OfflineGitHub()
        outbox = ExportOutbox(self.root / "outbox.sqlite3")
        publisher = GitHubPublisher(self.vault, client=fake, outbox=outbox)
        try:
            self.assertEqual(publisher.enqueue_accepted()["status"], "queued")
            result = publisher.publish_once()
            self.assertEqual(result["status"], "degraded")
            self.assertEqual(outbox.health()["pending"], 1)
        finally:
            publisher.close()
            outbox.close()

    def test_export_cycle_writes_health_without_touching_local_memory_policy(self):
        fake_publisher = Mock()
        fake_publisher.enqueue_accepted.return_value = {"status": "queued", "enqueued": 1}
        fake_publisher.publish_once.return_value = {"status": "degraded", "published": 0,
                                                     "errors": [{"reason": "offline"}]}
        with patch("memory_hub.github_export.GitHubPublisher", return_value=fake_publisher):
            result = run_once(self.vault)
        self.assertEqual(result["status"], "degraded")
        health = json.loads((self.root / "health.json").read_text(encoding="utf-8"))
        self.assertEqual(health["errors"][0]["reason"], "offline")
        fake_publisher.close.assert_called_once()

    def test_export_redacts_private_paths_and_secrets_and_skips_review_entries(self):
        self._store(1, changed_files=[r"C:\Users\vibm\private\secret.py", "src/safe.py"])
        payload = build_export_payloads(self.vault)[0]
        self.assertIn("[private path redacted]", payload["changed_files"])
        self.assertIn("src/safe.py", payload["changed_files"])
        self.assertNotIn("Users/vibm", json.dumps(payload))
        review = self.manager.propose_session({
            "model": "codex", "title": "Review only", "investigated": ["pending"],
            "learned": [], "completed": [], "next_steps": [], "project": "review-only",
            "session_group_id": "review-group", "checkpoint_id": "review-1", "sequence": 1,
            "entry_type": "checkpoint",
        }, write_mode="review")
        self.assertEqual(review["status"], "queued")
        self.assertEqual({item["session_group_id"] for item in build_export_payloads(self.vault)}, {"export-group"})


if __name__ == "__main__":
    unittest.main()
