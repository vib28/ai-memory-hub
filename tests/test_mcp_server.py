import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_hub import mcp_server


class McpServerTests(unittest.TestCase):
    def test_session_write_surfaces_application_rejection(self):
        rejected = {"status": "rejected", "reason": "empty memory"}
        with patch.object(mcp_server.manager, "propose_session", return_value=rejected):
            with self.assertRaisesRegex(ValueError, "session write rejected: empty memory"):
                mcp_server.session_write(
                    title="test",
                    investigated=["evidence"],
                    learned=["finding"],
                    completed=["result"],
                    next_steps=["next"],
                )

    def test_session_write_returns_queued_result(self):
        queued = {"status": "queued", "proposal": {"proposal_id": "p1"}}
        with patch.object(mcp_server.manager, "propose_session", return_value=queued):
            result = mcp_server.session_write(
                title="test",
                investigated=["evidence"],
                learned=["finding"],
                completed=["result"],
                next_steps=["next"],
            )
        self.assertEqual(result["status"], "queued")


    def test_pattern_match_surfaces_application_rejection(self):
        """Same contract as session_write: a rejection must not look like success (#23)."""
        rejected = {"status": "rejected", "reason": "secret detected", "half": "preference"}
        with patch.object(mcp_server.manager, "propose_pattern_match", return_value=rejected):
            with self.assertRaisesRegex(ValueError, r"pattern match rejected \(preference half\)"):
                mcp_server.propose_pattern_match(
                    pattern_id="regression", project_fact_text="fact",
                    preference_rule_text="rule", subject="demo")

    def test_pattern_match_returns_queued_result(self):
        queued = {"status": "queued", "proposal": {"proposal_id": "p1"}, "label": "first occurrence"}
        with patch.object(mcp_server.manager, "propose_pattern_match", return_value=queued):
            result = mcp_server.propose_pattern_match(
                pattern_id="regression", project_fact_text="fact",
                preference_rule_text="rule", subject="demo")
        self.assertEqual(result["status"], "queued")


class McpBoundaryTests(unittest.TestCase):
    """#21: clients reach the vault through public MCP tools, never through the manager.

    The manager stays importable inside the package (the MCP server and these tests use
    it) and by maintenance code that relocates existing records. What must not happen is
    a client-facing script proposing memory in-process, which is how #19 bypassed the
    configured write mode.
    """

    CLIENT_SCRIPTS = {"backfill_patterns.py"}

    def test_client_scripts_do_not_import_the_manager(self):
        scripts = Path(__file__).resolve().parent.parent / "scripts"
        offenders = []
        for path in sorted(scripts.glob("*.py")):
            if path.name not in self.CLIENT_SCRIPTS:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "memory_hub.manager":
                    offenders.append(f"{path.name}: from {node.module} import ...")
                elif isinstance(node, ast.Import):
                    offenders.extend(f"{path.name}: import {alias.name}"
                                     for alias in node.names
                                     if alias.name == "memory_hub.manager")
        self.assertEqual(offenders, [], "client scripts must submit through public MCP tools")


if __name__ == "__main__":
    unittest.main()
