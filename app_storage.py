# @author Cursor
from __future__ import annotations

import json
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from config import ConfigError, Settings, _validated_gitlab_url

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def default_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "review-bot"
        if sys.platform == "win32":
            return Path.home() / "AppData" / "Roaming" / "review-bot"
        return Path.home() / ".review-bot"
    return Path(__file__).resolve().parent / "app_data"


@dataclass
class GuiSettings:
    gitlab_token: str = ""
    openai_api_key: str = ""
    gitlab_url: str = ""
    log_level: str = "INFO"
    summary_max_lines: int = 30
    summary_max_chars: int = 3000

    def is_configured(self) -> bool:
        return bool(self.gitlab_token.strip() and self.openai_api_key.strip() and self.gitlab_url.strip())


@dataclass
class ProjectRow:
    id: str
    name: str = ""
    project_id: str = ""
    mr_iid: str = ""
    rules_filename: str = ""

    @staticmethod
    def create() -> "ProjectRow":
        return ProjectRow(id=uuid.uuid4().hex)


class AppStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_data_dir()
        self.settings_path = self.root / "settings.json"
        self.projects_path = self.root / "projects.json"
        self.rules_dir = self.root / "rules"

    def load_settings(self) -> GuiSettings:
        payload = self._read_json(self.settings_path)
        if not isinstance(payload, dict):
            return GuiSettings()
        return GuiSettings(
            gitlab_token=str(payload.get("gitlab_token", "")),
            openai_api_key=str(payload.get("openai_api_key", "")),
            gitlab_url=str(payload.get("gitlab_url", "")),
            log_level=str(payload.get("log_level", "INFO") or "INFO").upper(),
            summary_max_lines=_positive_int(payload.get("summary_max_lines"), 30),
            summary_max_chars=_positive_int(payload.get("summary_max_chars"), 3000),
        )

    def save_settings(self, settings: GuiSettings) -> GuiSettings:
        normalized = _normalize_settings(settings)
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(asdict(normalized), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return normalized

    def load_projects(self) -> list[ProjectRow]:
        payload = self._read_json(self.projects_path)
        if not isinstance(payload, list):
            return []
        rows: list[ProjectRow] = []
        for item in payload:
            if not isinstance(item, dict) or not str(item.get("id", "")).strip():
                continue
            rows.append(
                ProjectRow(
                    id=str(item["id"]),
                    name=str(item.get("name", "")),
                    project_id=str(item.get("project_id", "")),
                    mr_iid=str(item.get("mr_iid", "")),
                    rules_filename=str(item.get("rules_filename", "")),
                )
            )
        return rows

    def save_projects(self, rows: list[ProjectRow]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = [asdict(row) for row in rows]
        self.projects_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def rules_path(self, row_id: str) -> Path:
        return self.rules_dir / f"{row_id}.md"

    def has_rules(self, row_id: str) -> bool:
        return self.rules_path(row_id).is_file()

    def store_rules(self, row_id: str, source: Path) -> str:
        if not source.is_file():
            raise ConfigError(f"Rules file not found: {source}")
        self.rules_dir.mkdir(parents=True, exist_ok=True)
        destination = self.rules_path(row_id)
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        return source.name

    def delete_rules(self, row_id: str) -> None:
        path = self.rules_path(row_id)
        if path.exists():
            path.unlink()

    def _read_json(self, path: Path) -> object:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


def build_review_settings(gui_settings: GuiSettings, project_id: int, mr_iid: int) -> Settings:
    normalized = _normalize_settings(gui_settings)
    if not normalized.is_configured():
        raise ConfigError("GITLAB_TOKEN, OPENAI_API_KEY, and GITLAB_URL are required")
    host = (urlparse(normalized.gitlab_url).hostname or "").lower()
    gitlab_url = _validated_gitlab_url(normalized.gitlab_url, (host,) if host else ())
    return Settings(
        platform="gitlab",
        llm_provider="openai",
        gitlab_token=normalized.gitlab_token,
        project_id=project_id,
        mr_iid=mr_iid,
        openai_api_key=normalized.openai_api_key,
        gitlab_url=gitlab_url,
        model_name="gpt-5.3-codex",
        max_file_lines=3000,
        bot_username="review-bot",
        bot_user_id=None,
        fail_fast=False,
        dry_run=False,
        log_level=normalized.log_level,
        review_language="ja",
        gitlab_allowed_hosts=(host,),
        llm_blocked_paths=(),
        output_mode="both",
        summary_max_lines=normalized.summary_max_lines,
        summary_max_chars=normalized.summary_max_chars,
    )


def _normalize_settings(settings: GuiSettings) -> GuiSettings:
    log_level = settings.log_level.strip().upper() or "INFO"
    if log_level not in LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL must be one of: {', '.join(LOG_LEVELS)}")
    if settings.summary_max_lines < 1 or settings.summary_max_chars < 1:
        raise ConfigError("SUMMARY_MAX_LINES and SUMMARY_MAX_CHARS must be positive integers")
    gitlab_url = settings.gitlab_url.strip()
    if gitlab_url:
        host = (urlparse(gitlab_url).hostname or "").lower()
        gitlab_url = _validated_gitlab_url(gitlab_url, (host,) if host else ())
    return GuiSettings(
        gitlab_token=settings.gitlab_token.strip(),
        openai_api_key=settings.openai_api_key.strip(),
        gitlab_url=gitlab_url,
        log_level=log_level,
        summary_max_lines=settings.summary_max_lines,
        summary_max_chars=settings.summary_max_chars,
    )


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if parsed < 1:
        return default
    return parsed
