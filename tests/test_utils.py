# @author Cursor
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.ignore_parser import ReviewIgnore
from utils.rule_loader import load_rules


class UtilsTests(unittest.TestCase):
    def test_reviewignore_matches_path_and_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".reviewignore").write_text("*.lock\nbuild/**\n", encoding="utf-8")
            ignore = ReviewIgnore.from_file(root)

            self.assertTrue(ignore.should_ignore("yarn.lock"))
            self.assertTrue(ignore.should_ignore("build/output.txt"))
            self.assertFalse(ignore.should_ignore("src/main.py"))

    def test_load_rules_returns_empty_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(load_rules(root), "")

    def test_reviewignore_supports_negation_last_match_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".reviewignore").write_text("*.md\n!README.md\n", encoding="utf-8")
            ignore = ReviewIgnore.from_file(root)

            self.assertFalse(ignore.should_ignore("README.md"))
            self.assertTrue(ignore.should_ignore("docs.md"))

    def test_load_rules_merges_rules_dir_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rules.md").write_text("# Base\nRule A", encoding="utf-8")
            rules_dir = root / "rules.d"
            rules_dir.mkdir(parents=True, exist_ok=True)
            (rules_dir / "10-auth.md").write_text("Auth Rule", encoding="utf-8")
            (rules_dir / "20-db.md").write_text("DB Rule", encoding="utf-8")

            merged = load_rules(root)
            self.assertIn("# Base\nRule A", merged)
            self.assertIn("## From 10-auth.md", merged)
            self.assertIn("Auth Rule", merged)
            self.assertIn("## From 20-db.md", merged)
            self.assertIn("DB Rule", merged)


if __name__ == "__main__":
    unittest.main()
