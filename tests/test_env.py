from __future__ import annotations

import unittest
from unittest.mock import patch

from memory_hub._env import int_env


class IntEnvTests(unittest.TestCase):
    """#75: every MEMORY_* integer knob must degrade to its default, never raise."""

    def test_missing_variable_returns_default(self):
        with patch.dict("os.environ", {}, clear=False):
            self.assertEqual(int_env("MEMORY_DOES_NOT_EXIST", 42), 42)

    def test_valid_value_is_used(self):
        with patch.dict("os.environ", {"MEMORY_TEST_INT": "99"}):
            self.assertEqual(int_env("MEMORY_TEST_INT", 42), 99)

    def test_malformed_value_falls_back_to_default(self):
        with patch.dict("os.environ", {"MEMORY_TEST_INT": "6k"}):
            self.assertEqual(int_env("MEMORY_TEST_INT", 42), 42)

    def test_value_below_minimum_is_clamped(self):
        with patch.dict("os.environ", {"MEMORY_TEST_INT": "0"}):
            self.assertEqual(int_env("MEMORY_TEST_INT", 42, minimum=1), 1)


if __name__ == "__main__":
    unittest.main()
