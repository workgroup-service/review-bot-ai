# @author Cursor
from __future__ import annotations

import unittest
from unittest.mock import patch

from config import ConfigError, Settings
from review_factories import build_platform_client, build_review_engine


def _base_settings() -> Settings:
    return Settings(
        platform="gitlab",
        llm_provider="openai",
        gitlab_token="token",
        project_id=1,
        mr_iid=2,
        openai_api_key="sk-test",
        gitlab_url="https://gitlab.com",
    )


class ReviewFactoriesTests(unittest.TestCase):
    @patch("review_factories.GitLabReviewClient")
    def test_build_platform_client_gitlab_supported(self, mock_client) -> None:
        settings = _base_settings()
        instance = object()
        mock_client.return_value = instance

        client, exit_code = build_platform_client(settings)
        self.assertEqual(exit_code, 0)
        self.assertIs(client, instance)

    def test_build_platform_client_unsupported_platform(self) -> None:
        settings = _base_settings()
        settings = Settings(**{**settings.__dict__, "platform": "github"})
        client, exit_code = build_platform_client(settings)
        self.assertIsNone(client)
        self.assertEqual(exit_code, 2)

    @patch("review_factories.LLMReviewer")
    def test_build_review_engine_openai_supported(self, mock_reviewer) -> None:
        settings = _base_settings()
        instance = object()
        mock_reviewer.return_value = instance

        engine = build_review_engine(settings)
        self.assertIs(engine, instance)

    def test_build_review_engine_unsupported_provider(self) -> None:
        settings = _base_settings()
        settings = Settings(**{**settings.__dict__, "llm_provider": "anthropic"})
        with self.assertRaises(ConfigError):
            build_review_engine(settings)


if __name__ == "__main__":
    unittest.main()
