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
    platform: str
    llm_provider: str
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
    llm_blocked_paths: tuple[str, ...] = ()
    output_mode: str = "inline"
    summary_max_lines: int = 30
    summary_max_chars: int = 3000


def _env_or_default(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


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


def _review_platform(name: str = "REVIEW_PLATFORM", default: str = "gitlab") -> str:
    value = os.getenv(name, default).strip().lower() or default
    aliases = {
        "gitlab": "gitlab",
        "gl": "gitlab",
        "github": "github",
        "gh": "github",
    }
    normalized = aliases.get(value)
    if not normalized:
        raise ConfigError(f"{name} must be one of: gitlab, github")
    return normalized


def _llm_provider(name: str = "LLM_PROVIDER", default: str = "openai") -> str:
    value = os.getenv(name, default).strip().lower() or default
    aliases = {
        "openai": "openai",
        "open-api": "openai",
        "open_api": "openai",
        "openapi": "openai",
        "anthropic": "anthropic",
    }
    normalized = aliases.get(value)
    if not normalized:
        raise ConfigError(f"{name} must be one of: openai, anthropic")
    return normalized


def _output_mode(name: str = "OUTPUT_MODE", default: str = "inline") -> str:
    value = os.getenv(name, default).strip().lower() or default
    if value not in {"inline", "summary", "both"}:
        raise ConfigError(f"{name} must be one of: inline, summary, both")
    return value


def _parse_allowed_hosts(name: str = "GITLAB_ALLOWED_HOSTS") -> tuple[str, ...]:
    raw = os.getenv(name, "gitlab.com")
    hosts = [host.strip().lower() for host in raw.split(",") if host.strip()]
    if not hosts:
        raise ConfigError(f"{name} must include at least one hostname")
    return tuple(hosts)


def _parse_csv_patterns(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ()
    return tuple(pattern.strip() for pattern in raw.split(",") if pattern.strip())


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


def _load_required_values(
    platform: str, llm_provider: str
) -> tuple[str, int, int, str]:
    gitlab_token = ""
    project_id = 0
    mr_iid = 0
    openai_api_key = ""

    if platform == "gitlab":
        gitlab_token = _require("GITLAB_TOKEN")
        try:
            project_id = int(_require("PROJECT_ID"))
            mr_iid = int(_require("MR_IID"))
        except ValueError as exc:
            raise ConfigError("PROJECT_ID and MR_IID must be integers") from exc

    if llm_provider == "openai":
        openai_api_key = _require("OPENAI_API_KEY")

    return (gitlab_token, project_id, mr_iid, openai_api_key)


def _load_runtime_values() -> tuple[int, str, str, int | None, bool, bool, str, str, str, int, int]:
    try:
        max_file_lines = int(_env_or_default("MAX_FILE_LINES", "3000"))
    except ValueError as exc:
        raise ConfigError("MAX_FILE_LINES must be an integer") from exc

    try:
        summary_max_lines = int(_env_or_default("SUMMARY_MAX_LINES", "30"))
        summary_max_chars = int(_env_or_default("SUMMARY_MAX_CHARS", "3000"))
    except ValueError as exc:
        raise ConfigError("SUMMARY_MAX_LINES and SUMMARY_MAX_CHARS must be integers") from exc

    return (
        max_file_lines,
        _env_or_default("MODEL_NAME", "gpt-5.3-codex"),
        _env_or_default("BOT_USERNAME", "review-bot"),
        _optional_int("BOT_USER_ID"),
        _optional_bool("FAIL_FAST", default=False),
        _optional_bool("DRY_RUN", default=False),
        _env_or_default("LOG_LEVEL", "INFO").upper(),
        _review_language(),
        _output_mode(),
        summary_max_lines,
        summary_max_chars,
    )


def _load_security_values() -> tuple[str, tuple[str, ...]]:
    allowed_hosts = _parse_allowed_hosts()
    gitlab_url = _validated_gitlab_url(
        _env_or_default("GITLAB_URL", "https://gitlab.com"),
        allowed_hosts=allowed_hosts,
    )
    return gitlab_url, allowed_hosts


def load_settings() -> Settings:
    load_dotenv()
    platform = _review_platform()
    llm_provider = _llm_provider()
    gitlab_token, project_id, mr_iid, openai_api_key = _load_required_values(
        platform=platform,
        llm_provider=llm_provider,
    )
    (
        max_file_lines,
        model_name,
        bot_username,
        bot_user_id,
        fail_fast,
        dry_run,
        log_level,
        review_language,
        output_mode,
        summary_max_lines,
        summary_max_chars,
    ) = _load_runtime_values()
    gitlab_url, allowed_hosts = _load_security_values()
    llm_blocked_paths = _parse_csv_patterns("LLM_BLOCKED_PATHS")

    return Settings(
        platform=platform,
        llm_provider=llm_provider,
        gitlab_token=gitlab_token,
        project_id=project_id,
        mr_iid=mr_iid,
        openai_api_key=openai_api_key,
        gitlab_url=gitlab_url,
        model_name=model_name,
        max_file_lines=max_file_lines,
        bot_username=bot_username,
        bot_user_id=bot_user_id,
        fail_fast=fail_fast,
        dry_run=dry_run,
        log_level=log_level,
        review_language=review_language,
        gitlab_allowed_hosts=allowed_hosts,
        llm_blocked_paths=llm_blocked_paths,
        output_mode=output_mode,
        summary_max_lines=summary_max_lines,
        summary_max_chars=summary_max_chars,
    )
