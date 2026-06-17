# @author Cursor
from __future__ import annotations

import argparse
import fnmatch
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from config import ConfigError, Settings, load_settings
from gitlab_client import ChangedFile, ReviewComment, extract_added_lines
from review_factories import build_platform_client, build_review_engine
from review_interfaces import ReviewEngine, ReviewPlatformClient
from utils.ignore_parser import ReviewIgnore
from utils.rule_loader import load_rules


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Code Review Bot for GitLab MR")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root that contains rules.md and .reviewignore",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop immediately on first per-file processing error",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze and print results without posting comments",
    )
    return parser.parse_args()


def should_review_file(file: ChangedFile, ignore: ReviewIgnore, settings: Settings) -> tuple[bool, str]:
    if file.is_deleted:
        return False, "deleted file"
    if ignore.should_ignore(file.path):
        return False, "ignored by .reviewignore"
    if not file.diff.strip():
        return False, "empty diff"
    if file.new_line_count > settings.max_file_lines:
        return False, f"too large ({file.new_line_count} lines)"
    if _is_llm_blocked_path(file.path, settings.llm_blocked_paths):
        return False, "blocked by LLM_BLOCKED_PATHS"
    return True, ""


def _is_llm_blocked_path(path: str, patterns: tuple[str, ...]) -> bool:
    if not patterns:
        return False
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


@dataclass
class RunStats:
    reviewed_count: int = 0
    posted_count: int = 0
    skipped_count: int = 0


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(levelname)s: %(message)s",
    )


def _process_finding(
    client: ReviewPlatformClient,
    file: ChangedFile,
    finding: object,
    added_lines: set[int],
    existing_positions: set[tuple[str, int, str]],
    diff_refs: dict[str, str],
    effective_dry_run: bool,
) -> tuple[int, int]:
    line = finding.line
    if line not in added_lines:
        logging.debug(
            "Skip finding on %s:%s (line not in added hunk)",
            file.path,
            line,
        )
        return 0, 0

    comment = ReviewComment(
        path=file.path,
        line=line,
        body=finding.comment,
        severity=finding.severity,
        suggestion=finding.suggestion,
    )

    if client.is_duplicate(comment, existing_positions):
        logging.info("Duplicate skipped: %s:%s", file.path, line)
        return 0, 1

    if effective_dry_run:
        logging.info("[DRY-RUN] %s:%s %s", file.path, line, finding.comment)
        client.append_position_cache(comment, existing_positions)
        return 1, 0

    client.post_inline_comment(comment, diff_refs)
    client.append_position_cache(comment, existing_positions)
    logging.info("Posted comment: %s:%s", file.path, line)
    return 1, 0


def _review_single_file(
    file: ChangedFile,
    client: ReviewPlatformClient,
    reviewer: ReviewEngine,
    rules_text: str,
    existing_positions: set[tuple[str, int, str]],
    diff_refs: dict[str, str],
    effective_dry_run: bool,
) -> tuple[int, int]:
    added_lines = extract_added_lines(file.diff)
    findings = reviewer.review_diff(path=file.path, diff=file.diff, rules_text=rules_text)

    posted_delta = 0
    skipped_delta = 0
    for finding in findings:
        posted_inc, skipped_inc = _process_finding(
            client=client,
            file=file,
            finding=finding,
            added_lines=added_lines,
            existing_positions=existing_positions,
            diff_refs=diff_refs,
            effective_dry_run=effective_dry_run,
        )
        posted_delta += posted_inc
        skipped_delta += skipped_inc
    return posted_delta, skipped_delta


def main() -> int:
    args = parse_args()

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    effective_dry_run = settings.dry_run or args.dry_run
    effective_fail_fast = settings.fail_fast or args.fail_fast

    _configure_logging(settings)

    repo_root = Path(args.repo_root).resolve()
    rules_text = load_rules(repo_root)
    ignore = ReviewIgnore.from_file(repo_root)

    client, client_exit_code = build_platform_client(settings)
    if client_exit_code != 0 or client is None:
        return client_exit_code

    try:
        reviewer = build_review_engine(settings)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    existing_positions = client.get_existing_bot_positions()
    diff_refs = client.get_diff_refs()

    files = client.get_changed_files()
    stats = RunStats()

    for file in files:
        should_review, reason = should_review_file(file, ignore, settings)
        if not should_review:
            stats.skipped_count += 1
            logging.info("Skip %s: %s", file.path, reason)
            continue

        stats.reviewed_count += 1
        try:
            posted_delta, skipped_delta = _review_single_file(
                file=file,
                client=client,
                reviewer=reviewer,
                rules_text=rules_text,
                existing_positions=existing_positions,
                diff_refs=diff_refs,
                effective_dry_run=effective_dry_run,
            )
            stats.posted_count += posted_delta
            stats.skipped_count += skipped_delta
        except Exception as exc:  # noqa: BLE001
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                logging.exception("Failed to process %s: %s", file.path, exc)
            else:
                logging.error("Failed to process %s: %s", file.path, exc)
            if effective_fail_fast:
                return 1

    print(
        "Review completed: "
        f"total_files={len(files)} reviewed_files={stats.reviewed_count} "
        f"posted={stats.posted_count} skipped={stats.skipped_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
