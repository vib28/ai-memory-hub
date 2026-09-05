import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from memory_hub.utils import file_lock, safe_join

class SafeJoinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parent_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            safe_join(self.root, "../outside.md")

    def test_absolute_path_is_confined_to_root(self):
        # Treated as vault-relative once the leading slash is stripped. Compare
        # against the resolved root, since safe_join resolves internally and a
        # temp dir may itself be a symlink/junction (e.g. CI runners' TEMP).
        p = safe_join(self.root, "/topics/thing.md")
        self.assertTrue(str(p).startswith(str(self.root.resolve())))

    def test_backslash_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            safe_join(self.root, "..\\..\\outside.md")

class StaleLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.target = Path(self.tmp.name) / "file.md"
        self.target.write_text("x", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_lock_from_dead_pid_is_stolen_not_timed_out(self):
        # Spawn and kill a real process so its PID is guaranteed free, then leave
        # a lock file behind claiming that dead PID (as a crash would).
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        dead_pid = proc.pid
        proc.terminate()
        proc.wait(timeout=5)

        lock = self.target.with_suffix(self.target.suffix + ".lock")
        lock.write_text(str(dead_pid), encoding="ascii")

        with file_lock(self.target, timeout=2.0):
            pass  # must not raise TimeoutError
        self.assertFalse(lock.exists())

if __name__ == "__main__":
    unittest.main()
