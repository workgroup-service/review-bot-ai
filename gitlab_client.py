# @author Cursor
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import gitlab

from config import Settings

SUMMARY_MARKER = "<!-- review-bot-summary -->"


@dataclass(frozen=True)
class ChangedFile:
    path: str
    diff: str
    new_line_count: int
    is_deleted: bool


@dataclass(frozen=True)
class ReviewComment:
    path: str
    line: int
    body: str
    severity: str
    suggestion: str | None = None


class GitLabReviewClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._gl = gitlab.Gitlab(url=settings.gitlab_url, private_token=settings.gitlab_token)
        self._project = self._gl.projects.get(settings.project_id)
        self._mr = self._project.mergerequests.get(settings.mr_iid)

    def get_changed_files(self) -> list[ChangedFile]:
        changes = self._mr.changes(get_all=True).get("changes", [])
        files: list[ChangedFile] = []
        for change in changes:
            diff = (change.get("diff") or "").strip("\n")
            path = change.get("new_path") or change.get("old_path")
            if not path:
                continue
            new_line_count = _count_new_file_lines(diff)
            files.append(
                ChangedFile(
                    path=path,
                    diff=diff,
                    new_line_count=new_line_count,
                    is_deleted=bool(change.get("deleted_file", False)),
                )
            )
        return files

    def get_diff_refs(self) -> dict[str, str]:
        refs = self._mr.attributes.get("diff_refs", {})
        if not refs:
            raise RuntimeError("MR diff_refs not found; cannot create inline comments.")
        return refs

    def get_existing_bot_positions(self) -> set[tuple[str, int, str]]:
        positions: set[tuple[str, int, str]] = set()
        discussions = self._mr.discussions.list(get_all=True)
        for discussion in discussions:
            notes = discussion.attributes.get("notes", [])
            for note in notes:
                if not self._is_bot_note(note):
                    continue
                position = note.get("position") or {}
                path = position.get("new_path")
                line = position.get("new_line")
                if not path or not line:
                    continue
                body = note.get("body", "")
                positions.add((path, int(line), _body_hash(body)))
        return positions

    def post_inline_comment(self, comment: ReviewComment, diff_refs: dict[str, str]) -> None:
        payload = {
            "body": _format_body(comment),
            "position": {
                "position_type": "text",
                "base_sha": diff_refs["base_sha"],
                "start_sha": diff_refs["start_sha"],
                "head_sha": diff_refs["head_sha"],
                "new_path": comment.path,
                "new_line": comment.line,
            },
        }
        self._mr.discussions.create(payload)

    def upsert_summary(self, summary_body: str) -> None:
        body = f"{SUMMARY_MARKER}\n{summary_body.strip()}"
        existing = self._find_existing_summary_note()
        if existing is None:
            self._mr.notes.create({"body": body})
            return
        existing.body = body
        existing.save()

    def is_duplicate(
        self, comment: ReviewComment, existing_positions: set[tuple[str, int, str]]
    ) -> bool:
        return _position_key(comment) in existing_positions

    def append_position_cache(
        self, comment: ReviewComment, existing_positions: set[tuple[str, int, str]]
    ) -> None:
        existing_positions.add(_position_key(comment))

    def _is_bot_note(self, note: dict[str, Any]) -> bool:
        author = note.get("author", {})
        if self._settings.bot_user_id and author.get("id") == self._settings.bot_user_id:
            return True
        username = author.get("username", "")
        return username == self._settings.bot_username

    def _find_existing_summary_note(self):  # noqa: ANN202
        notes = self._mr.notes.list(get_all=True)
        for note in notes:
            attrs = getattr(note, "attributes", {}) or {}
            body = attrs.get("body", "")
            if SUMMARY_MARKER not in body:
                continue
            author = attrs.get("author", {})
            if self._settings.bot_user_id and author.get("id") == self._settings.bot_user_id:
                return note
            if author.get("username", "") == self._settings.bot_username:
                return note
        return None


def _count_new_file_lines(diff: str) -> int:
    count = 0
    for line in diff.splitlines():
        if line.startswith("+++ ") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            count += 1
    return count


def extract_added_lines(diff: str) -> set[int]:
    """
    Parse unified diff and return line numbers in new file where additions happened.
    """
    added_lines: set[int] = set()
    current_new_line = 0

    for line in diff.splitlines():
        if line.startswith("@@"):
            # Example: @@ -10,4 +10,6 @@
            try:
                right = line.split("+", maxsplit=1)[1].split(" ", maxsplit=1)[0]
                current_new_line = int(right.split(",")[0])
            except (IndexError, ValueError):
                logging.debug("Could not parse hunk header: %s", line)
                current_new_line = 0
            continue

        if line.startswith("+") and not line.startswith("+++ "):
            if current_new_line > 0:
                added_lines.add(current_new_line)
            current_new_line += 1
        elif line.startswith("-") and not line.startswith("--- "):
            continue
        else:
            current_new_line += 1

    return added_lines


def _format_body(comment: ReviewComment) -> str:
    badge = _severity_badge(comment.severity)
    prefix = f"{badge}\n\n{comment.body.strip()}"
    if comment.suggestion:
        suggestion = comment.suggestion.strip("\n")
        return f"{prefix}\n\n```suggestion\n{suggestion}\n```"
    return prefix


def _position_key(comment: ReviewComment) -> tuple[str, int, str]:
    return (comment.path, comment.line, _body_hash(_format_body(comment)))


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _severity_badge(severity: str) -> str:
    normalized = severity.lower().strip()
    if normalized == "high":
        return "![must](https://img.shields.io/badge/review-fix-red?style=flat-square)"
    if normalized == "medium":
        return "![caution](https://img.shields.io/badge/review-caution-yellow?style=flat-square)"
    return "![tips](https://img.shields.io/badge/review-tips-blue?style=flat-square)"
