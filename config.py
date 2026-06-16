# @author Cursor
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    gitlab_token: str
    project_id: int
    mr_iid: int
    openai_api_key: str
    gitlab_url: str = "https://gitlab.com"
    model_name: str = "gpt-5.3-codex"
    max_file_lines: int = 3000
    bot_username: str = "review-bot"
    bot_user_id: int | None = None
    fail_fast: bool = False
    dry_run: bool = False
    log_level: str = "INFO"
    review_language: str = "ja"
    gitlab_allowed_hosts: tuple[str, ...] = ("gitlab.com",)


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got: {raw}") from exc


def _optional_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _review_language(name: str = "REVIEW_LANGUAGE", default: str = "ja") -> str:
    value = os.getenv(name, default).strip().lower() or default
    aliases = {
        "ja": "ja",
        "jp": "ja",
        "japanese": "ja",
        "en": "en",
        "english": "en",
    }
    normalized = aliases.get(value)
    if not normalized:
        raise ConfigError(f"{name} must be one of: ja, en")
    return normalized


def _parse_allowed_hosts(name: str = "GITLAB_ALLOWED_HOSTS") -> tuple[str, ...]:
    raw = os.getenv(name, "gitlab.com")
    hosts = [host.strip().lower() for host in raw.split(",") if host.strip()]
    if not hosts:
        raise ConfigError(f"{name} must include at least one hostname")
    return tuple(hosts)


def _validated_gitlab_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ConfigError("GITLAB_URL must use https scheme")
    if parsed.username or parsed.password:
        raise ConfigError("GITLAB_URL must not include credentials")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ConfigError("GITLAB_URL must include a hostname")
    if host not in allowed_hosts:
        allowlist = ", ".join(allowed_hosts)
        raise ConfigError(
            f"GITLAB_URL host '{host}' is not allowed. Set GITLAB_ALLOWED_HOSTS to include it. "
            f"Allowed: {allowlist}"
        )
    return parsed.geturl().rstrip("/")


def load_settings() -> Settings:
    load_dotenv()
    allowed_hosts = _parse_allowed_hosts()

    try:
        project_id = int(_require("PROJECT_ID"))
        mr_iid = int(_require("MR_IID"))
        max_file_lines = int(os.getenv("MAX_FILE_LINES", "3000"))
    except ValueError as exc:
        raise ConfigError("PROJECT_ID, MR_IID, and MAX_FILE_LINES must be integers") from exc

    return Settings(
        gitlab_token=_require("GITLAB_TOKEN"),
        project_id=project_id,
        mr_iid=mr_iid,
        openai_api_key=_require("OPENAI_API_KEY"),
        gitlab_url=_validated_gitlab_url(
            os.getenv("GITLAB_URL", "https://gitlab.com").strip() or "https://gitlab.com",
            allowed_hosts=allowed_hosts,
        ),
        model_name=os.getenv("MODEL_NAME", "gpt-5.3-codex").strip() or "gpt-5.3-codex",
        max_file_lines=max_file_lines,
        bot_username=os.getenv("BOT_USERNAME", "review-bot").strip() or "review-bot",
        bot_user_id=_optional_int("BOT_USER_ID"),
        fail_fast=_optional_bool("FAIL_FAST", default=False),
        dry_run=_optional_bool("DRY_RUN", default=False),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        review_language=_review_language(),
        gitlab_allowed_hosts=allowed_hosts,
    )
