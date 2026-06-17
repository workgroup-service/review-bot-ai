# @author Cursor
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import ConfigError, _validated_gitlab_url, load_settings


class ConfigTests(unittest.TestCase):
    def test_validated_gitlab_url_requires_https(self) -> None:
        with self.assertRaises(ConfigError):
            _validated_gitlab_url("http://gitlab.com", ("gitlab.com",))

    def test_validated_gitlab_url_rejects_host_outside_allowlist(self) -> None:
        with self.assertRaises(ConfigError):
            _validated_gitlab_url("https://example.com", ("gitlab.com",))

    def test_validated_gitlab_url_accepts_allowlisted_host(self) -> None:
        actual = _validated_gitlab_url("https://gitlab.example.com/", ("gitlab.example.com",))
        self.assertEqual(actual, "https://gitlab.example.com")

    def test_load_settings_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / ".env"
            config_file.write_text(
                "GITLAB_TOKEN=token\nPROJECT_ID=1\nMR_IID=2\nOPENAI_API_KEY=sk-test\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(config_path=str(config_file))

        self.assertEqual(settings.gitlab_url, "https://gitlab.com")
        self.assertEqual(settings.gitlab_allowed_hosts, ("gitlab.com",))
        self.assertEqual(settings.platform, "gitlab")
        self.assertEqual(settings.llm_provider, "openai")
        self.assertEqual(settings.llm_blocked_paths, ())
        self.assertEqual(settings.output_mode, "inline")
        self.assertEqual(settings.summary_max_lines, 30)
        self.assertEqual(settings.summary_max_chars, 3000)
        self.assertEqual(settings.model_name, "gpt-5.3-codex")
        self.assertEqual(settings.max_file_lines, 3000)
        self.assertEqual(settings.review_language, "ja")

    def test_load_settings_accepts_openapi_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / ".env"
            config_file.write_text(
                "REVIEW_PLATFORM=gitlab\n"
                "LLM_PROVIDER=openapi\n"
                "GITLAB_TOKEN=token\n"
                "PROJECT_ID=1\n"
                "MR_IID=2\n"
                "OPENAI_API_KEY=sk-test\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(config_path=str(config_file))
        self.assertEqual(settings.llm_provider, "openai")

    def test_load_settings_parses_llm_blocked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / ".env"
            config_file.write_text(
                "GITLAB_TOKEN=token\n"
                "PROJECT_ID=1\n"
                "MR_IID=2\n"
                "OPENAI_API_KEY=sk-test\n"
                "LLM_BLOCKED_PATHS=secrets/**, **/*.pem\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(config_path=str(config_file))
        self.assertEqual(settings.llm_blocked_paths, ("secrets/**", "**/*.pem"))

    def test_load_settings_parses_output_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / ".env"
            config_file.write_text(
                "GITLAB_TOKEN=token\n"
                "PROJECT_ID=1\n"
                "MR_IID=2\n"
                "OPENAI_API_KEY=sk-test\n"
                "OUTPUT_MODE=both\n"
                "SUMMARY_MAX_LINES=10\n"
                "SUMMARY_MAX_CHARS=500\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(config_path=str(config_file))
        self.assertEqual(settings.output_mode, "both")
        self.assertEqual(settings.summary_max_lines, 10)
        self.assertEqual(settings.summary_max_chars, 500)

    def test_load_settings_raises_when_config_file_missing(self) -> None:
        with self.assertRaises(ConfigError):
            load_settings(config_path="/tmp/not_found_review_bot.env")

    def test_load_settings_raises_when_config_file_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / ".env"
            config_file.write_text("NOT_A_VALID_LINE\nGITLAB_TOKEN=token\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_settings(config_path=str(config_file))


if __name__ == "__main__":
    unittest.main()
