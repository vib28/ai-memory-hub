from __future__ import annotations

import json
import unittest

from memory_hub.consolidator import ConsolidationError, consolidate_session, fallback_session


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ConsolidatorTests(unittest.TestCase):
    OBSERVATIONS = [
        {"session_id": "s1", "project": "demo", "tool": "Read", "files": ["src/a.py"],
         "output_summary": "Inspected authentication flow."},
        {"session_id": "s1", "project": "demo", "tool": "Edit", "files": ["src/a.py"],
         "output_summary": "Added refresh-token validation."},
    ]

    def test_without_model_uses_deterministic_fallback(self):
        payload = consolidate_session(self.OBSERVATIONS, base_url="", model="")
        self.assertEqual(payload["project"], "demo")
        self.assertTrue(payload["completed"])
        self.assertIn("src/a.py", payload["investigated"][0])

    def test_local_model_response_is_validated(self):
        def opener(*args, **kwargs):
            return FakeResponse({"choices": [{"message": {"content": json.dumps({
                "title": "Auth refresh",
                "project": "demo",
                "investigated": ["Reviewed auth"],
                "learned": ["Refresh tokens need validation"],
                "completed": ["Updated auth flow"],
                "next_steps": [],
            })}}]})

        payload = consolidate_session(self.OBSERVATIONS, base_url="http://local/v1", model="small", opener=opener)
        self.assertEqual(payload["title"], "Auth refresh")
        self.assertEqual(payload["next_steps"], [])

    def test_empty_observations_are_rejected(self):
        with self.assertRaises(ConsolidationError):
            fallback_session([])


if __name__ == "__main__":
    unittest.main()
