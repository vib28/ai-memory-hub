import unittest
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


if __name__ == "__main__":
    unittest.main()
