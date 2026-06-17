# @author Cursor
from __future__ import annotations

import os
import unittest
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
        env = {
            "GITLAB_TOKEN": "token",
            "PROJECT_ID": "1",
            "MR_IID": "2",
            "OPENAI_API_KEY": "sk-test",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("config.load_dotenv", return_value=True):
                settings = load_settings()

        self.assertEqual(settings.gitlab_url, "https://gitlab.com")
        self.assertEqual(settings.gitlab_allowed_hosts, ("gitlab.com",))
        self.assertEqual(settings.platform, "gitlab")
        self.assertEqual(settings.llm_provider, "openai")
        self.assertEqual(settings.llm_blocked_paths, ())
        self.assertEqual(settings.model_name, "gpt-5.3-codex")
        self.assertEqual(settings.max_file_lines, 3000)
        self.assertEqual(settings.review_language, "ja")

    def test_load_settings_accepts_openapi_alias(self) -> None:
        env = {
            "REVIEW_PLATFORM": "gitlab",
            "LLM_PROVIDER": "openapi",
            "GITLAB_TOKEN": "token",
            "PROJECT_ID": "1",
            "MR_IID": "2",
            "OPENAI_API_KEY": "sk-test",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("config.load_dotenv", return_value=True):
                settings = load_settings()
        self.assertEqual(settings.llm_provider, "openai")

    def test_load_settings_parses_llm_blocked_paths(self) -> None:
        env = {
            "GITLAB_TOKEN": "token",
            "PROJECT_ID": "1",
            "MR_IID": "2",
            "OPENAI_API_KEY": "sk-test",
            "LLM_BLOCKED_PATHS": "secrets/**, **/*.pem",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("config.load_dotenv", return_value=True):
                settings = load_settings()
        self.assertEqual(settings.llm_blocked_paths, ("secrets/**", "**/*.pem"))


if __name__ == "__main__":
    unittest.main()
