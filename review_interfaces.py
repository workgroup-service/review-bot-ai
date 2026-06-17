# @author Cursor
from __future__ import annotations

from typing import Protocol

from gitlab_client import ChangedFile, ReviewComment
from llm_reviewer import ReviewFinding


class ReviewPlatformClient(Protocol):
    def get_changed_files(self) -> list[ChangedFile]:
        ...

    def get_diff_refs(self) -> dict[str, str]:
        ...

    def get_existing_bot_positions(self) -> set[tuple[str, int, str]]:
        ...

    def post_inline_comment(self, comment: ReviewComment, diff_refs: dict[str, str]) -> None:
        ...

    def is_duplicate(
        self, comment: ReviewComment, existing_positions: set[tuple[str, int, str]]
    ) -> bool:
        ...

    def append_position_cache(
        self, comment: ReviewComment, existing_positions: set[tuple[str, int, str]]
    ) -> None:
        ...

    def upsert_summary(self, summary_body: str) -> None:
        ...


class ReviewEngine(Protocol):
    def review_diff(self, path: str, diff: str, rules_text: str) -> list[ReviewFinding]:
        ...
