import tempfile
import unittest
from pathlib import Path

from scripts.sync_client_prompts import CLIENTS, sync_prompts


class PromptSyncTests(unittest.TestCase):
    def test_sync_is_deterministic_and_preserves_writer_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            prompts = Path(temporary)
            generic = (
                "# Shared instructions\n\n"
                "Writer identity for this client: `<tool-name>`.\n"
            )
            (prompts / "generic.md").write_text(generic, encoding="utf-8")

            sync_prompts(prompts)
            first = {name: (prompts / f"{name}.md").read_text(encoding="utf-8") for name in CLIENTS}
            sync_prompts(prompts)
            second = {name: (prompts / f"{name}.md").read_text(encoding="utf-8") for name in CLIENTS}

            self.assertEqual(first, second)
            for client in CLIENTS:
                identity = "<tool-name>" if client == "generic" else client
                self.assertIn(f"Writer identity for this client: `{identity}`.", first[client])


if __name__ == "__main__":
    unittest.main()
