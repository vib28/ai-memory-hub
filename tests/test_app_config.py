from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_hub.app_config import (
    bootstrap_environment,
    config_path,
    effective_config,
    load_config_file,
    normalize_values,
    save_config_file,
    save_settings,
)


class AppConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_config_file_missing_returns_empty(self):
        self.assertEqual(load_config_file(self.vault), {})

    def test_save_and_load_round_trip(self):
        save_config_file(self.vault, {"MEMORY_WRITER": "codex"})
        self.assertEqual(load_config_file(self.vault), {"MEMORY_WRITER": "codex"})
        self.assertTrue(config_path(self.vault).exists())

    def test_load_config_file_tolerates_corrupt_json(self):
        path = config_path(self.vault)
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(load_config_file(self.vault), {})

    def test_bootstrap_environment_fills_gaps_without_overriding_explicit_env(self):
        save_config_file(self.vault, {"MEMORY_WRITER": "codex", "MEMORY_WRITE_MODE": "auto"})
        with patch.dict("os.environ", {"MEMORY_WRITER": "claude"}, clear=False):
            os.environ.pop("MEMORY_WRITE_MODE", None)
            bootstrap_environment(self.vault)
            self.assertEqual(os.environ["MEMORY_WRITER"], "claude")  # explicit env var wins
            self.assertEqual(os.environ["MEMORY_WRITE_MODE"], "auto")  # file fills the gap

    def test_bootstrap_environment_is_a_safe_noop_for_falsy_vault_or_missing_file(self):
        bootstrap_environment(None)  # must not raise
        bootstrap_environment(self.vault)  # no config.json yet either

    def test_bootstrap_environment_ignores_unknown_and_empty_values(self):
        save_config_file(self.vault, {"NOT_A_REAL_SETTING": "x", "MEMORY_WRITER": ""})
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("NOT_A_REAL_SETTING", None)
            os.environ.pop("MEMORY_WRITER", None)
            bootstrap_environment(self.vault)
            self.assertNotIn("NOT_A_REAL_SETTING", os.environ)
            self.assertNotIn("MEMORY_WRITER", os.environ)

    def test_normalize_values_coerces_and_validates_each_type(self):
        normalized = normalize_values({
            "MEMORY_VAULT_HISTORY": "true",  # bool from a truthy-looking string
            "MEMORY_WORKER_FLUSH_SECONDS": "90",  # int from a numeric string
            "MEMORY_WRITE_MODE": "auto",  # select
            "MEMORY_LLM_MODEL": None,  # text: None -> ""
            "NOT_A_REAL_SETTING": "ignored",  # unknown key dropped silently
        })
        self.assertEqual(normalized, {
            "MEMORY_VAULT_HISTORY": True,
            "MEMORY_WORKER_FLUSH_SECONDS": 90,
            "MEMORY_WRITE_MODE": "auto",
            "MEMORY_LLM_MODEL": "",
        })

    def test_normalize_values_rejects_out_of_range_int(self):
        with self.assertRaisesRegex(ValueError, "MEMORY_WORKER_FLUSH_SECONDS"):
            normalize_values({"MEMORY_WORKER_FLUSH_SECONDS": 999999})

    def test_normalize_values_rejects_non_numeric_int(self):
        with self.assertRaisesRegex(ValueError, "whole number"):
            normalize_values({"MEMORY_WORKER_FLUSH_SECONDS": "not-a-number"})

    def test_normalize_values_rejects_value_outside_select_options(self):
        with self.assertRaisesRegex(ValueError, "MEMORY_WRITE_MODE"):
            normalize_values({"MEMORY_WRITE_MODE": "sometimes"})

    def test_effective_config_precedence_file_over_env_over_default(self):
        save_config_file(self.vault, {"MEMORY_WRITER": "codex"})
        with patch.dict("os.environ", {"MEMORY_WRITE_MODE": "auto"}, clear=False):
            os.environ.pop("MEMORY_WRITER", None)
            rows = {row["key"]: row for row in effective_config(self.vault)}
        self.assertEqual(rows["MEMORY_WRITER"]["value"], "codex")
        self.assertEqual(rows["MEMORY_WRITER"]["source"], "file")
        self.assertEqual(rows["MEMORY_WRITE_MODE"]["value"], "auto")
        self.assertEqual(rows["MEMORY_WRITE_MODE"]["source"], "env")
        self.assertEqual(rows["MEMORY_EMBED_MODEL"]["source"], "default")

    def test_effective_config_coerces_env_sourced_bool_to_a_real_boolean(self):
        """#config-ui: an env var is always textual ("false"); a bool-type setting
        must still reach the frontend as a real JSON boolean, or a JS checkbox
        treats the non-empty string "false" as truthy and renders checked."""
        with patch.dict("os.environ", {"MEMORY_VAULT_HISTORY": "false"}, clear=False):
            rows = {row["key"]: row for row in effective_config(self.vault)}
        self.assertIs(rows["MEMORY_VAULT_HISTORY"]["value"], False)
        self.assertEqual(rows["MEMORY_VAULT_HISTORY"]["source"], "env")

    def test_effective_config_coerces_env_sourced_int(self):
        with patch.dict("os.environ", {"MEMORY_WORKER_BATCH_LIMIT": "250"}, clear=False):
            rows = {row["key"]: row for row in effective_config(self.vault)}
        self.assertEqual(rows["MEMORY_WORKER_BATCH_LIMIT"]["value"], 250)
        self.assertIsInstance(rows["MEMORY_WORKER_BATCH_LIMIT"]["value"], int)

    def test_save_settings_merges_without_wiping_other_keys(self):
        save_config_file(self.vault, {"MEMORY_WRITER": "codex", "MEMORY_WRITE_MODE": "auto"})
        save_settings(self.vault, {"MEMORY_WRITER": "gemini"})
        on_disk = load_config_file(self.vault)
        self.assertEqual(on_disk["MEMORY_WRITER"], "gemini")
        self.assertEqual(on_disk["MEMORY_WRITE_MODE"], "auto")  # untouched

    def test_save_settings_returns_the_new_effective_config(self):
        rows = {row["key"]: row for row in save_settings(self.vault, {"MEMORY_WRITER": "qwen"})}
        self.assertEqual(rows["MEMORY_WRITER"]["value"], "qwen")
        self.assertEqual(rows["MEMORY_WRITER"]["source"], "file")

    def test_save_settings_rejects_invalid_value_without_writing(self):
        with self.assertRaises(ValueError):
            save_settings(self.vault, {"MEMORY_DASHBOARD_PORT": 999999})
        self.assertEqual(load_config_file(self.vault), {})


if __name__ == "__main__":
    unittest.main()
