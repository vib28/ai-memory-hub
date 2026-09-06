import tempfile
import unittest
from pathlib import Path

from memory_hub.entities import load_entity_aliases, resolve_subject


class EntityAliasRegistryTests(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(load_entity_aliases(Path(tempfile.mkdtemp()) / "nope.md"), {})

    def test_seed_template_parses_as_empty(self):
        """Regression guard: an earlier draft of this template embedded its
        format example as a real-looking '## kind: id' heading, which this
        parser (deliberately naive about Markdown fencing) read as live data --
        every vault initialized from the template would have silently started
        with a fake 'git-safety' alias already registered. The example must
        stay indented, never at column 0, or this test catches it again."""
        seed = Path(__file__).resolve().parent.parent / "vault_template" / "entity-aliases.md"
        self.assertEqual(load_entity_aliases(seed), {})

    def test_load_and_resolve_roundtrip(self):
        path = Path(tempfile.mkdtemp()) / "entity-aliases.md"
        path.write_text(
            "## preference: git-safety\n"
            "- git-safety-checks\n"
            "- confirm-destructive-ops\n\n"
            "## profile: primary-os\n"
            "- primary-development-os\n",
            encoding="utf-8",
        )
        registry = load_entity_aliases(path)
        self.assertEqual(resolve_subject(registry, "preference", "git-safety-checks"), "git-safety")
        self.assertEqual(resolve_subject(registry, "preference", "confirm-destructive-ops"), "git-safety")
        self.assertEqual(resolve_subject(registry, "preference", "git-safety"), "git-safety")
        self.assertEqual(resolve_subject(registry, "profile", "primary-development-os"), "primary-os")
        # An unregistered subject resolves to itself, and kinds don't leak into
        # each other's alias sets.
        self.assertEqual(resolve_subject(registry, "preference", "unrelated-subject"), "unrelated-subject")
        self.assertEqual(resolve_subject(registry, "profile", "git-safety-checks"), "git-safety-checks")


if __name__ == "__main__":
    unittest.main()
