"""Project identity resolution (#84)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from memory_hub.project_resolver import (
    UNSCOPED, ProjectIdentity, clear_cache, resolve_project, resolve_project_cached,
)


class ProjectResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        clear_cache()

    def tearDown(self):
        self.tmp.cleanup()

    def _repo(self, name: str, *, git: bool = True) -> Path:
        repo = self.root / "code" / name
        (repo / "src" / "pkg").mkdir(parents=True)
        if git:
            (repo / ".git").mkdir()
        return repo

    def test_git_repository_root_subdirectory_and_worktree_share_one_slug(self):
        repo = self._repo("My Cool App")
        worktree = self.root / "code" / "my-cool-app-feature"
        (worktree / "lib").mkdir(parents=True)
        (worktree / ".git").write_text(
            f"gitdir: {repo / '.git' / 'worktrees' / 'feature'}\n", encoding="utf-8")
        for start in (repo, repo / "src" / "pkg", worktree, worktree / "lib"):
            with self.subTest(start=start):
                identity = resolve_project(start)
                self.assertEqual(identity.project, "my-cool-app")
                self.assertEqual(identity.source, "git")
        self.assertEqual(resolve_project(worktree).worktree, str(worktree))
        self.assertEqual(resolve_project(repo / "src").worktree, str(repo))

    def test_package_marker_without_git(self):
        project = self.root / "code" / "svc"
        (project / "app").mkdir(parents=True)
        (project / "pyproject.toml").write_text("[project]\nname='svc'\n", encoding="utf-8")
        identity = resolve_project(project / "app")
        self.assertEqual((identity.project, identity.source), ("svc", "marker"))

    def test_pin_file_beats_directory_name(self):
        repo = self._repo("checkout-dir-name")
        (repo / ".ai-memory-project").write_text("# canonical\nintuicryp-hermes\n", encoding="utf-8")
        identity = resolve_project(repo / "src")
        self.assertEqual((identity.project, identity.source), ("intuicryp-hermes", "pin"))

    def test_vault_override_beats_everything_and_prefers_longest_prefix(self):
        repo = self._repo("nested")
        inner = repo / "src" / "pkg"
        vault = self.root / "vault"
        (vault / ".ai-memory-hub").mkdir(parents=True)
        (vault / ".ai-memory-hub" / "projects.json").write_text(json.dumps({
            str(repo): "outer-name",
            str(inner): "inner-name",
        }), encoding="utf-8")
        self.assertEqual(resolve_project(inner, vault=vault).project, "inner-name")
        self.assertEqual(resolve_project(repo / "src", vault=vault).project, "outer-name")
        self.assertEqual(resolve_project(repo / "src", vault=vault).source, "override")
        # A corrupt override file must not break resolution.
        (vault / ".ai-memory-hub" / "projects.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(resolve_project(inner, vault=vault).project, "nested")

    def test_explicit_project_is_honoured(self):
        repo = self._repo("whatever")
        identity = resolve_project(repo, explicit="Trading Agent")
        self.assertEqual((identity.project, identity.source), ("trading-agent", "explicit"))

    def test_non_project_directories_are_unscoped_and_never_merged(self):
        for path in (Path.home(), Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"
                     if os.name == "nt" else Path("/tmp")):
            with self.subTest(path=path):
                identity = resolve_project(path)
                self.assertEqual(identity.project, UNSCOPED)
        self.assertEqual(resolve_project(None).project, UNSCOPED)
        self.assertEqual(resolve_project("").project, UNSCOPED)

    def test_vanished_directory_still_resolves_deterministically(self):
        identity = resolve_project(self.root / "gone" / "ghost-project")
        self.assertEqual((identity.project, identity.source), ("ghost-project", "cwd"))

    def test_windows_case_and_separator_variants_agree(self):
        repo = self._repo("CaseTest")
        a = resolve_project(str(repo).replace("\\", "/"))
        b = resolve_project(str(repo).upper() if os.name == "nt" else str(repo))
        self.assertEqual(a.project, b.project)

    def test_cached_variant_returns_identical_result(self):
        repo = self._repo("cached")
        self.assertEqual(resolve_project_cached(repo / "src"), resolve_project(repo / "src"))
        self.assertIsInstance(resolve_project_cached(repo), ProjectIdentity)

    def test_no_git_or_network_is_required(self):
        # The resolver never shells out; a PATH without git must not matter.
        repo = self._repo("offline")
        old = os.environ.get("PATH")
        try:
            os.environ["PATH"] = ""
            self.assertEqual(resolve_project(repo).project, "offline")
        finally:
            if old is not None:
                os.environ["PATH"] = old


if __name__ == "__main__":
    unittest.main()
