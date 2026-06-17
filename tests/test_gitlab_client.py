# @author Cursor
from __future__ import annotations

import unittest

from gitlab_client import ReviewComment, _format_body


class GitLabClientFormatTests(unittest.TestCase):
    def test_format_body_starts_with_badge_then_blank_line(self) -> None:
        body = _format_body(
            ReviewComment(
                path="app.py",
                line=10,
                body="Fix null handling.",
                severity="high",
                suggestion=None,
            )
        )
        self.assertTrue(body.startswith("![must]("))
        self.assertIn("\n\nFix null handling.", body)

    def test_format_body_appends_suggestion_block(self) -> None:
        body = _format_body(
            ReviewComment(
                path="app.py",
                line=10,
                body="Use safe call.",
                severity="medium",
                suggestion="value = obj?.name",
            )
        )
        self.assertIn("![caution](", body)
        self.assertIn("```suggestion\nvalue = obj?.name\n```", body)


if __name__ == "__main__":
    unittest.main()
