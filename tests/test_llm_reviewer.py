# @author Cursor
from __future__ import annotations

import unittest

from llm_reviewer import _mask_sensitive_text, _normalize_severity


class LLMReviewerHelpersTests(unittest.TestCase):
    def test_mask_sensitive_text_masks_key_value_pairs(self) -> None:
        source = "api_key=abc123456 password: supersecret token=mytoken123"
        actual = _mask_sensitive_text(source)
        self.assertIn("api_key=[REDACTED]", actual)
        self.assertIn("password: [REDACTED]", actual)
        self.assertIn("token=[REDACTED]", actual)

    def test_mask_sensitive_text_masks_jwt(self) -> None:
        source = "auth eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdEFGH1234.qwertyQWERTY9876"
        actual = _mask_sensitive_text(source)
        self.assertIn("[REDACTED_JWT]", actual)

    def test_mask_sensitive_text_masks_private_key_block(self) -> None:
        source = "-----BEGIN PRIVATE KEY-----\nABCDEF\n-----END PRIVATE KEY-----"
        actual = _mask_sensitive_text(source)
        self.assertIn("[REDACTED]", actual)

    def test_normalize_severity_upgrades_security_words_to_high(self) -> None:
        severity = _normalize_severity("low", "this leaks token to logs", None)
        self.assertEqual(severity, "high")

    def test_normalize_severity_upgrades_low_perf_issue_to_medium(self) -> None:
        severity = _normalize_severity("low", "possible n+1 performance regression", "fix")
        self.assertEqual(severity, "medium")

    def test_normalize_severity_keeps_low_when_has_suggestion_and_low_risk(self) -> None:
        severity = _normalize_severity("low", "rename local variable", "val count = total")
        self.assertEqual(severity, "low")


if __name__ == "__main__":
    unittest.main()
