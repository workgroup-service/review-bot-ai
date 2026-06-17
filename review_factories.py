# @author Cursor
from __future__ import annotations

import sys
from typing import Optional

from gitlab.exceptions import GitlabAuthenticationError, GitlabGetError

from config import ConfigError, Settings
from gitlab_client import GitLabReviewClient
from llm_reviewer import LLMReviewer
from review_interfaces import ReviewEngine, ReviewPlatformClient


def build_platform_client(settings: Settings) -> tuple[Optional[ReviewPlatformClient], int]:
    if settings.platform != "gitlab":
        print(
            f"Configured REVIEW_PLATFORM='{settings.platform}' is not implemented yet. "
            "Currently supported: gitlab",
            file=sys.stderr,
        )
        return None, 2

    try:
        return GitLabReviewClient(settings), 0
    except GitlabAuthenticationError:
        print(
            "GitLab authentication failed. "
            "Check GITLAB_TOKEN scope and expiration.",
            file=sys.stderr,
        )
        return None, 2
    except GitlabGetError as exc:
        print(
            "GitLab resource not found (404) while loading project/MR.\n"
            f"GITLAB_URL={settings.gitlab_url}\n"
            f"PROJECT_ID={settings.project_id}\n"
            f"MR_IID={settings.mr_iid}\n"
            "Please verify: project ID, MR IID, and token access to the project.\n"
            f"Original error: {exc}",
            file=sys.stderr,
        )
        return None, 2


def build_review_engine(settings: Settings) -> ReviewEngine:
    if settings.llm_provider != "openai":
        raise ConfigError(
            f"Configured LLM_PROVIDER='{settings.llm_provider}' is not implemented yet. "
            "Currently supported: openai"
        )
    return LLMReviewer(
        model_name=settings.model_name,
        api_key=settings.openai_api_key,
        review_language=settings.review_language,
    )
