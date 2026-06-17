# @author Cursor
from __future__ import annotations

import unittest

from main import _is_llm_blocked_path


class MainHelpersTests(unittest.TestCase):
    def test_is_llm_blocked_path_returns_false_when_patterns_empty(self) -> None:
        self.assertFalse(_is_llm_blocked_path("src/app.py", ()))

    def test_is_llm_blocked_path_matches_glob_patterns(self) -> None:
        patterns = ("secrets/**", "**/*.pem")
        self.assertTrue(_is_llm_blocked_path("secrets/config.json", patterns))
        self.assertTrue(_is_llm_blocked_path("infra/cert.pem", patterns))
        self.assertFalse(_is_llm_blocked_path("src/main.py", patterns))


if __name__ == "__main__":
    unittest.main()
