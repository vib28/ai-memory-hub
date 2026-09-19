"""Tests for the auto-fix feature: scan_audit_issues, fix_issue, GitHub issue
creation, and the dashboard's /api/fix-issue and /api/audit/issues endpoints.
"""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from memory_hub.auto_fix import (
    _build_issue_body,
    _classify_malformed_line,
    _create_github_issue,
    apply_fix,
    build_issue_title,
    fix_issue,
    issues_dir,
    record_issue,
    scan_audit_issues,
)
from memory_hub.dashboard import DashboardHandler
from memory_hub.manager import MemoryManager


class MalformedLineClassificationTests(unittest.TestCase):
    """Verify the raw browser-automation payload pattern detection."""

    def test_browser_payload_screenshot(self):
        line = '- [{"text": "Successfully captured screenshot...", "type": "text"}, ...]'
        assert _classify_malformed_line(line) == "browser-payload-leak"

    def test_browser_payload_clicked(self):
        line = '- [{"text": "Clicked at (1178, 39)", "type": "text"}]'
        assert _classify_malformed_line(line) == "browser-payload-leak"

    def test_browser_payload_navigated(self):
        line = '- [{"text": "Navigated to https://example.com", "type": "text"}]'
        assert _classify_malformed_line(line) == "browser-payload-leak"

    def test_browser_payload_selector(self):
        line = '- [{"text": "Found selector #submit-btn", "type": "text"}]'
        assert _classify_malformed_line(line) == "browser-payload-leak"

    def test_browser_payload_executed(self):
        line = '- [{"text": "Successfully executed JavaScript...", "type": "text"}]'
        assert _classify_malformed_line(line) == "browser-payload-leak"

    def test_plain_bracket_entry(self):
        line = '- [{"foo": "bar"}]'
        assert _classify_malformed_line(line) == "malformed-bracket-entry"

    def test_malformed_list_entry(self):
        line = '- [something] some text'
        assert _classify_malformed_line(line) == "malformed-list-entry"

    def test_generic_malformed(self):
        line = '- [garbage'
        # Still matches the bracket pattern so it's classified as a list entry
        assert _classify_malformed_line(line) == "malformed-list-entry"

    def test_non_list_generic(self):
        line = 'random text without dash-bracket'
        assert _classify_malformed_line(line) == "malformed-line"


class IssueBodyTests(unittest.TestCase):
    """Verify the seven-level GitHub issue body format."""

    def test_build_issue_body_has_seven_levels(self):
        issue = {
            "issue_type": "browser-payload-leak",
            "severity": "warning",
            "fixable": True,
            "summary": "Malformed memory line in /sessions/other.md (line 42)",
            "path": "/sessions/other.md",
            "line": 42,
            "text": '- [{"text": "Clicked somewhere", "type": "text"}]',
        }
        body = _build_issue_body(issue)
        for level in ("## 1. Summary", "## 2. Affected location", "## 3. Evidence",
                       "## 4. Classification", "## 5. Proposed fix",
                       "## 6. Risks / trade-offs", "## 7. References"):
            assert level in body, f"Missing section: {level}"

    def test_build_issue_body_escapes_code_block(self):
        issue = {
            "issue_type": "orphan-session-block",
            "severity": "info",
            "fixable": True,
            "summary": "Orphan session block",
            "path": "/sessions/other.md",
            "heading": "my-session",
        }
        body = _build_issue_body(issue)
        assert "orphan-session-block" in body
        assert "`/sessions/other.md`" in body

    def test_build_issue_title(self):
        issue = {"issue_type": "orphan-session-block", "summary": "Test orphan"}
        title = build_issue_title(issue)
        assert title.startswith("[auto-fix]")
        assert "orphan-session-block" in title


class ScanAuditIssuesTests(unittest.TestCase):
    """Verify audit findings are correctly expanded into issue dicts."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="auto_fix_test_")
        self.vault = Path(self.tmp_dir) / "vault"
        self.manager = MemoryManager(self.vault)
        template = Path(__file__).resolve().parent.parent / "vault_template"
        self.manager.initialize(template)

    def tearDown(self):
        self.manager.close()
        import shutil
        try:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        except Exception:
            pass

    def _inject_malformed_line(self, path: str, line_text: str, line_num: int = 3):
        """Inject a malformed line into a vault file, creating it if needed."""
        vault_path = self.manager.vault.resolve(path)
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        if vault_path.exists():
            content = vault_path.read_text(encoding="utf-8")
        else:
            # Create a minimal topics file with proper frontmatter
            content = "---\ntype: topic\n---\n# Topic\n"
        lines = content.splitlines()
        # Insert the malformed line at the right position
        while len(lines) < line_num:
            lines.append("")
        lines.insert(line_num - 1, line_text)
        vault_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.manager.reindex()

    def test_scan_detects_browser_payload(self):
        browser_line = '- [{"text": "Successfully captured screenshot of element", "type": "text"}]'
        self._inject_malformed_line("/topics/security.md", browser_line)
        issues = scan_audit_issues(self.manager)
        types = [i["issue_type"] for i in issues]
        assert "browser-payload-leak" in types
        leak = next(i for i in issues if i["issue_type"] == "browser-payload-leak")
        assert leak["fixable"]
        assert leak["path"] == "/topics/security.md"

    def test_scan_detects_malformed_bracket_entry(self):
        line = '- [{"foo": "bar"}]'
        self._inject_malformed_line("/topics/security.md", line)
        issues = scan_audit_issues(self.manager)
        types = [i["issue_type"] for i in issues]
        assert "malformed-bracket-entry" in types

    def test_scan_detects_orphan_session_block(self):
        session_path = self.manager.vault.resolve("/sessions/other.md")
        session_path.parent.mkdir(parents=True, exist_ok=True)
        existing = ""
        if session_path.exists():
            existing = session_path.read_text(encoding="utf-8")
        else:
            # Create a minimal session file with proper frontmatter
            existing = "---\ntype: session\n---\n# Sessions\n"
        new_content = existing.rstrip() + "\n\n## orphan-heading-123\n**Model:** test\nNo session marker here.\n"
        session_path.write_text(new_content, encoding="utf-8")
        self.manager.reindex()
        issues = scan_audit_issues(self.manager)
        types = [i["issue_type"] for i in issues]
        assert "orphan-session-block" in types
        orphan = next(i for i in issues if i["issue_type"] == "orphan-session-block")
        assert orphan["fixable"]
        assert orphan["heading"] == "orphan-heading-123"

    def test_healthy_vault_returns_no_issues(self):
        # Fresh vault should have no issues
        issues = scan_audit_issues(self.manager)
        assert issues == []


class ApplyFixTests(unittest.TestCase):
    """Verify apply_fix correctly modifies vault files."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="auto_fix_test_")
        self.vault = Path(self.tmp_dir) / "vault"
        self.manager = MemoryManager(self.vault)
        template = Path(__file__).resolve().parent.parent / "vault_template"
        self.manager.initialize(template)

    def tearDown(self):
        self.manager.close()
        import shutil
        try:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        except Exception:
            pass

    def _inject_malformed_line(self, path: str, line_text: str, line_num: int = 3):
        """Inject a malformed line into a vault file, creating it if needed."""
        vault_path = self.manager.vault.resolve(path)
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        if vault_path.exists():
            content = vault_path.read_text(encoding="utf-8")
        else:
            # Create a minimal topics file with proper frontmatter
            content = "---\ntype: topic\n---\n# Topic\n"
        lines = content.splitlines()
        while len(lines) < line_num:
            lines.append("")
        lines.insert(line_num - 1, line_text)
        vault_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.manager.reindex()

    def test_apply_fix_deletes_browser_payload(self):
        browser_line = '- [{"text": "Successfully captured screenshot", "type": "text"}]'
        self._inject_malformed_line("/topics/security.md", browser_line, line_num=3)
        issue = {
            "issue_type": "browser-payload-leak",
            "severity": "warning",
            "fixable": True,
            "summary": "test",
            "path": "/topics/security.md",
            "line": 3,
            "text": browser_line,
        }
        result = apply_fix(self.manager, issue)
        assert result["status"] == "fixed"
        # Verify the line was removed
        content = self.manager.vault.read("/topics/security.md")
        assert "Successfully captured screenshot" not in content

    def test_apply_fix_deletes_orphan_session_block(self):
        session_path = self.manager.vault.resolve("/sessions/other.md")
        session_path.parent.mkdir(parents=True, exist_ok=True)
        existing = ""
        if session_path.exists():
            existing = session_path.read_text(encoding="utf-8")
        else:
            existing = "---\ntype: session\n---\n# Sessions\n"
        new_content = existing.rstrip() + "\n\n## orphan-test-block\n**Model:** test\nBody text without marker.\n"
        session_path.write_text(new_content, encoding="utf-8")
        self.manager.reindex()
        issue = {
            "issue_type": "orphan-session-block",
            "severity": "info",
            "fixable": True,
            "summary": "test",
            "path": "/sessions/other.md",
            "heading": "orphan-test-block",
        }
        result = apply_fix(self.manager, issue)
        assert result["status"] == "fixed"
        content = self.manager.vault.read("/sessions/other.md")
        assert "orphan-test-block" not in content

    def test_apply_fix_duplicate_is_manual(self):
        issue = {
            "issue_type": "duplicate-memory-id",
            "severity": "error",
            "fixable": False,
            "summary": "duplicate",
            "memory_id": "abc123",
        }
        result = apply_fix(self.manager, issue)
        assert result["status"] == "manual"

    def test_apply_fix_missing_from_index_reindexes(self):
        # Write a valid entry directly to disk (bypassing the manager)
        vault_path = self.manager.vault.resolve("/preferences.md")
        content = vault_path.read_text(encoding="utf-8")
        # Add a valid entry line
        new_entry = "- [stated] Test manual entry <!-- mem:test-manual-123 source:user date:2026-01-01 -->"
        new_content = content.rstrip() + "\n" + new_entry + "\n"
        vault_path.write_text(new_content, encoding="utf-8")
        # Don't reindex - the audit should now show this as missing from index
        issue = {
            "issue_type": "missing-from-index",
            "severity": "warning",
            "fixable": True,
            "summary": "test",
            "memory_id": "test-manual-123",
        }
        result = apply_fix(self.manager, issue)
        assert result["status"] == "fixed"

    def test_apply_fix_refuses_well_formed_line(self):
        # A line that looks like a bracket but is well-formed should not be deleted
        # First create the file since topics/security.md doesn't exist in the template
        vault_path = self.manager.vault.resolve("/topics/security.md")
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        vault_path.write_text("---\ntype: topic\n---\n# Security\n", encoding="utf-8")
        issue = {
            "issue_type": "browser-payload-leak",
            "severity": "warning",
            "fixable": True,
            "summary": "test",
            "path": "/topics/security.md",
            "line": 1,  # Frontmatter line
            "text": "type: topic",
        }
        result = apply_fix(self.manager, issue)
        assert result["status"] == "skipped"

    def test_apply_fix_already_gone(self):
        issue = {
            "issue_type": "browser-payload-leak",
            "severity": "warning",
            "fixable": True,
            "summary": "test",
            "path": "/topics/security.md",
            "line": 999,
            "text": "- [{garbage]",
        }
        result = apply_fix(self.manager, issue)
        assert result["status"] == "skipped"


class RecordIssueTests(unittest.TestCase):
    """Verify issue records are persisted to .ai-memory-hub/issues/."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="auto_fix_test_")
        self.vault = Path(self.tmp_dir) / "vault"
        self.vault.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil
        try:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        except Exception:
            pass

    def test_record_issue_creates_file(self):
        issue = {
            "issue_type": "browser-payload-leak",
            "severity": "warning",
            "fixable": True,
            "summary": "test",
            "path": "/topics/test.md",
            "line": 3,
        }
        github = {"skipped": True, "reason": "test"}
        issue_id = record_issue(self.vault, issue, github)
        target = issues_dir(self.vault) / f"{issue_id}.json"
        assert target.exists()
        record = json.loads(target.read_text(encoding="utf-8"))
        assert record["issue_type"] == "browser-payload-leak"
        assert record["github"]["reason"] == "test"
        assert not record["fixed"]


class GitHubIssueTests(unittest.TestCase):
    """Verify _create_github_issue handles various repo configurations."""

    def test_skipped_when_no_repo(self):
        issue = {"issue_type": "browser-payload-leak", "fixable": True,
                 "summary": "test", "vault_path": None}
        result = _create_github_issue(issue)
        assert result["skipped"]

    def test_skips_when_vault_has_no_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir(parents=True)
            issue = {"issue_type": "browser-payload-leak", "fixable": True,
                     "summary": "test", "vault_path": str(vault)}
            result = _create_github_issue(issue)
            assert result["skipped"]

    def test_creates_issue_with_mock_client(self):

        issue = {
            "issue_type": "browser-payload-leak",
            "fixable": True,
            "summary": "test summary",
            "severity": "warning",
            "path": "/topics/test.md",
            "line": 3,
        }

        class FakeClient:
            def create_issue(self, title, body):
                return {"number": 99, "html_url": "https://github.com/owner/repo/issues/99"}

        result = _create_github_issue(issue, repo="owner/repo", client_factory=FakeClient)
        assert not result["skipped"]
        assert result["number"] == 99

    def test_handles_github_failure(self):
        issue = {
            "issue_type": "browser-payload-leak",
            "fixable": True,
            "summary": "test summary",
            "severity": "warning",
            "path": "/topics/test.md",
        }

        def failing_factory():
            raise RuntimeError("gh CLI not found")

        result = _create_github_issue(issue, repo="owner/repo", client_factory=failing_factory)
        assert result["skipped"]
        assert "gh CLI not found" in result["reason"]


class FixIssueEndToEndTests(unittest.TestCase):
    """End-to-end: scan -> fix -> verify."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="auto_fix_test_")
        self.vault = Path(self.tmp_dir) / "vault"
        self.manager = MemoryManager(self.vault)
        template = Path(__file__).resolve().parent.parent / "vault_template"
        self.manager.initialize(template)

    def tearDown(self):
        self.manager.close()
        import shutil
        try:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        except Exception:
            pass

    def test_fix_issue_end_to_end(self):
        # Inject a browser payload
        browser_line = '- [{"text": "Clicked at (100, 200)", "type": "text"}]'
        vault_path = self.manager.vault.resolve("/topics/security.md")
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        if not vault_path.exists():
            vault_path.write_text("---\ntype: topic\n---\n# Security\n", encoding="utf-8")
        content = vault_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        lines.insert(2, browser_line)
        vault_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.manager.reindex()

        # Verify it's in the audit
        issues = scan_audit_issues(self.manager)
        leak = next(i for i in issues if i["issue_type"] == "browser-payload-leak")

        # Fix it
        result = fix_issue(
            self.manager,
            issue_type="browser-payload-leak",
            summary=leak["summary"],
            severity="warning",
            fixable=True,
            path=leak["path"],
            line=leak["line"],
            text=leak["text"],
        )
        assert result["fix"]["status"] == "fixed"
        # Verify the line was removed from disk
        content = self.manager.vault.read("/topics/security.md")
        assert "Clicked at" not in content
        # Verify the issue was recorded
        target = issues_dir(self.vault) / f"{result['issue_id']}.json"
        assert target.exists()


class DashboardFixEndpointTests(unittest.TestCase):
    """Integration tests for the dashboard's /api/fix-issue endpoint."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="auto_fix_test_")
        self.vault = Path(self.tmp_dir) / "vault"
        self.manager = MemoryManager(self.vault)
        template = Path(__file__).resolve().parent.parent / "vault_template"
        self.manager.initialize(template)

        DashboardHandler.manager = self.manager
        DashboardHandler.launch_token = "test-token"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        DashboardHandler.allowed_hosts = frozenset({f"127.0.0.1:{self.httpd.server_address[1]}"})
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.thread.join(timeout=5)
        self.httpd.server_close()
        self.manager.close()
        import shutil
        try:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        except Exception:
            pass

    def _post(self, path, headers, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1])
        conn.request("POST", path, body=json.dumps(payload or {}), headers=headers)
        resp = conn.getresponse()
        status, body = resp.status, resp.read()
        conn.close()
        return status, body

    def _get(self, path, headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1])
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        status, body = resp.status, resp.read()
        conn.close()
        return status, body

    def test_fix_issue_endpoint_creates_record(self):
        headers = {
            "Host": f"127.0.0.1:{self.httpd.server_address[1]}",
            "X-Launch-Token": "test-token",
        }
        # First inject a malformed line
        browser_line = '- [{"text": "Successfully executed script", "type": "text"}]'
        vault_path = self.manager.vault.resolve("/topics/security.md")
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        if not vault_path.exists():
            vault_path.write_text("---\ntype: topic\n---\n# Security\n", encoding="utf-8")
        content = vault_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        lines.insert(2, browser_line)
        vault_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.manager.reindex()

        # Get the audit issues to find the line number
        issues = scan_audit_issues(self.manager)
        leak = next(i for i in issues if i["issue_type"] == "browser-payload-leak")

        # Call the endpoint
        payload = {
            "issue_type": leak["issue_type"],
            "summary": leak["summary"],
            "severity": "warning",
            "fixable": True,
            "path": leak["path"],
            "line": leak["line"],
            "text": leak["text"],
        }
        status, body = self._post("/api/fix-issue", headers, payload)
        assert status == 200
        result = json.loads(body)
        assert result["fix"]["status"] == "fixed"
        assert "issue_id" in result

        # Verify the file was fixed
        content = self.manager.vault.read("/topics/security.md")
        assert "Successfully executed script" not in content

        # Verify the record was created
        target = issues_dir(self.vault) / f"{result['issue_id']}.json"
        assert target.exists()

    def test_audit_issues_endpoint(self):
        headers = {
            "Host": f"127.0.0.1:{self.httpd.server_address[1]}",
            "X-Launch-Token": "test-token",
        }
        # Inject a malformed line
        browser_line = '- [{"text": "Clicked somewhere", "type": "text"}]'
        vault_path = self.manager.vault.resolve("/topics/security.md")
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        if not vault_path.exists():
            vault_path.write_text("---\ntype: topic\n---\n# Security\n", encoding="utf-8")
        content = vault_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        lines.insert(2, browser_line)
        vault_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.manager.reindex()

        status, body = self._get("/api/audit/issues", headers)
        assert status == 200
        data = json.loads(body)
        assert "issues" in data
        types = [i["issue_type"] for i in data["issues"]]
        assert "browser-payload-leak" in types


if __name__ == "__main__":
    unittest.main()
