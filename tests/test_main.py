# @author Cursor
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from main import _is_llm_blocked_path, _resolve_optional_file


class MainHelpersTests(unittest.TestCase):
    def test_is_llm_blocked_path_returns_false_when_patterns_empty(self) -> None:
        self.assertFalse(_is_llm_blocked_path("src/app.py", ()))

    def test_is_llm_blocked_path_matches_glob_patterns(self) -> None:
        patterns = ("secrets/**", "**/*.pem")
        self.assertTrue(_is_llm_blocked_path("secrets/config.json", patterns))
        self.assertTrue(_is_llm_blocked_path("infra/cert.pem", patterns))
        self.assertFalse(_is_llm_blocked_path("src/main.py", patterns))

    def test_resolve_optional_file_returns_default_under_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            resolved = _resolve_optional_file(repo_root, "", "rules.md")
            self.assertEqual(resolved, (repo_root / "rules.md").resolve())

    def test_resolve_optional_file_resolves_relative_override_from_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            resolved = _resolve_optional_file(repo_root, "configs/custom-rules.md", "rules.md")
            self.assertEqual(resolved, (repo_root / "configs/custom-rules.md").resolve())

    def test_resolve_optional_file_keeps_absolute_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            absolute = str((repo_root / "external.env").resolve())
            resolved = _resolve_optional_file(repo_root, absolute, "rules.md")
            self.assertEqual(resolved, Path(absolute))


if __name__ == "__main__":
    unittest.main()
