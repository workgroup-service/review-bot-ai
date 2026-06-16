# @author Cursor
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from gitlab.exceptions import GitlabAuthenticationError, GitlabGetError

from config import ConfigError, Settings, load_settings
from gitlab_client import ChangedFile, GitLabReviewClient, ReviewComment, extract_added_lines
from llm_reviewer import LLMReviewer
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
    return True, ""


def main() -> int:
    args = parse_args()

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    effective_dry_run = settings.dry_run or args.dry_run
    effective_fail_fast = settings.fail_fast or args.fail_fast

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(levelname)s: %(message)s",
    )

    repo_root = Path(args.repo_root).resolve()
    rules_text = load_rules(repo_root)
    ignore = ReviewIgnore.from_file(repo_root)

    try:
        client = GitLabReviewClient(settings)
    except GitlabAuthenticationError:
        print(
            "GitLab authentication failed. "
            "Check GITLAB_TOKEN scope and expiration.",
            file=sys.stderr,
        )
        return 2
    except GitlabGetError as exc:
        # GitLab often returns 404 when resource is missing OR access is denied.
        print(
            "GitLab resource not found (404) while loading project/MR.\n"
            f"GITLAB_URL={settings.gitlab_url}\n"
            f"PROJECT_ID={settings.project_id}\n"
            f"MR_IID={settings.mr_iid}\n"
            "Please verify: project ID, MR IID, and token access to the project.\n"
            f"Original error: {exc}",
            file=sys.stderr,
        )
        return 2

    reviewer = LLMReviewer(
        model_name=settings.model_name,
        api_key=settings.openai_api_key,
        review_language=settings.review_language,
    )
    existing_positions = client.get_existing_bot_positions()
    diff_refs = client.get_diff_refs()

    files = client.get_changed_files()
    reviewed_count = 0
    posted_count = 0
    skipped_count = 0

    for file in files:
        should_review, reason = should_review_file(file, ignore, settings)
        if not should_review:
            skipped_count += 1
            logging.info("Skip %s: %s", file.path, reason)
            continue

        reviewed_count += 1
        try:
            added_lines = extract_added_lines(file.diff)
            findings = reviewer.review_diff(path=file.path, diff=file.diff, rules_text=rules_text)

            for finding in findings:
                if finding.line not in added_lines:
                    logging.debug(
                        "Skip finding on %s:%s (line not in added hunk)",
                        file.path,
                        finding.line,
                    )
                    continue

                comment = ReviewComment(
                    path=file.path,
                    line=finding.line,
                    body=finding.comment,
                    severity=finding.severity,
                    suggestion=finding.suggestion,
                )

                if client.is_duplicate(comment, existing_positions):
                    skipped_count += 1
                    logging.info("Duplicate skipped: %s:%s", file.path, finding.line)
                    continue

                if effective_dry_run:
                    posted_count += 1
                    logging.info("[DRY-RUN] %s:%s %s", file.path, finding.line, finding.comment)
                    client.append_position_cache(comment, existing_positions)
                    continue

                client.post_inline_comment(comment, diff_refs)
                posted_count += 1
                client.append_position_cache(comment, existing_positions)
                logging.info("Posted comment: %s:%s", file.path, finding.line)
        except Exception as exc:  # noqa: BLE001
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                logging.exception("Failed to process %s: %s", file.path, exc)
            else:
                logging.error("Failed to process %s: %s", file.path, exc)
            if effective_fail_fast:
                return 1

    print(
        "Review completed: "
        f"total_files={len(files)} reviewed_files={reviewed_count} "
        f"posted={posted_count} skipped={skipped_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
