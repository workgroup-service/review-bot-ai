# @author Cursor
from __future__ import annotations

import argparse
import fnmatch
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from config import ConfigError, Settings, load_settings
from gitlab_client import ChangedFile, ReviewComment, extract_added_lines
from llm_reviewer import _mask_sensitive_text
from review_factories import build_platform_client, build_review_engine
from review_interfaces import ReviewEngine, ReviewPlatformClient
from utils.ignore_parser import ReviewIgnore
from utils.rule_loader import load_rules


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Code Review Bot for GitLab MR")
    parser.add_argument(
        "--config",
        default=".env",
        help="Path to environment config file (default: .env)",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root that contains rules.md and .reviewignore",
    )
    parser.add_argument(
        "--rules-file",
        default="",
        help="Path to rules file (default: <repo-root>/rules.md)",
    )
    parser.add_argument(
        "--reviewignore-file",
        default="",
        help="Path to review ignore file (default: <repo-root>/.reviewignore)",
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


def _resolve_optional_file(repo_root: Path, override_path: str, default_name: str) -> Path:
    if not override_path.strip():
        return (repo_root / default_name).resolve()
    path = Path(override_path).expanduser()
    if path.is_absolute():
        return path
    return (repo_root / path).resolve()


@dataclass
class RunStats:
    reviewed_count: int = 0
    posted_count: int = 0
    skipped_count: int = 0
    findings_total: int = 0
    severity_counts: Counter = field(default_factory=Counter)
    top_findings: list[tuple[str, int, str, str]] = field(default_factory=list)
    skipped_reasons: Counter = field(default_factory=Counter)


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(levelname)s: %(message)s",
    )


def _process_finding(
    client: ReviewPlatformClient,
    file: ChangedFile,
    comment: ReviewComment,
    added_lines: set[int],
    existing_positions: set[tuple[str, int, str]],
    diff_refs: dict[str, str],
    effective_dry_run: bool,
) -> tuple[int, int]:
    line = comment.line
    if line not in added_lines:
        logging.debug(
            "Skip finding on %s:%s (line not in added hunk)",
            file.path,
            line,
        )
        return 0, 0

    if client.is_duplicate(comment, existing_positions):
        logging.info("Duplicate skipped: %s:%s", file.path, line)
        return 0, 1

    if effective_dry_run:
        logging.info("[DRY-RUN] %s:%s %s", file.path, line, comment.body)
        client.append_position_cache(comment, existing_positions)
        return 1, 0

    client.post_inline_comment(comment, diff_refs)
    client.append_position_cache(comment, existing_positions)
    logging.info("Posted comment: %s:%s", file.path, line)
    return 1, 0


def _should_post_inline(settings: Settings) -> bool:
    return settings.output_mode in {"inline", "both"}


def _should_post_summary(settings: Settings) -> bool:
    return settings.output_mode in {"summary", "both"}


def _review_single_file(
    file: ChangedFile,
    client: ReviewPlatformClient,
    reviewer: ReviewEngine,
    rules_text: str,
    existing_positions: set[tuple[str, int, str]],
    diff_refs: dict[str, str],
    effective_dry_run: bool,
    allow_inline_post: bool,
) -> tuple[int, int, list[ReviewComment]]:
    added_lines = extract_added_lines(file.diff)
    findings = reviewer.review_diff(path=file.path, diff=file.diff, rules_text=rules_text)

    posted_delta = 0
    skipped_delta = 0
    emitted_comments: list[ReviewComment] = []
    for finding in findings:
        line = finding.line
        if line not in added_lines:
            logging.debug(
                "Skip finding on %s:%s (line not in added hunk)",
                file.path,
                line,
            )
            continue
        comment = ReviewComment(
            path=file.path,
            line=line,
            body=finding.comment,
            severity=finding.severity,
            suggestion=finding.suggestion,
        )
        emitted_comments.append(comment)

        if not allow_inline_post:
            continue

        posted_inc, skipped_inc = _process_finding(
            client=client,
            file=file,
            comment=comment,
            added_lines=added_lines,
            existing_positions=existing_positions,
            diff_refs=diff_refs,
            effective_dry_run=effective_dry_run,
        )
        posted_delta += posted_inc
        skipped_delta += skipped_inc
    return posted_delta, skipped_delta, emitted_comments


def _severity_rank(severity: str) -> int:
    if severity == "high":
        return 3
    if severity == "medium":
        return 2
    return 1


def _record_summary_candidates(stats: RunStats, comments: list[ReviewComment]) -> None:
    for comment in comments:
        stats.findings_total += 1
        stats.severity_counts[comment.severity] += 1
        stats.top_findings.append((comment.severity, comment.line, comment.path, comment.body))


def _build_summary(stats: RunStats, total_files: int, settings: Settings) -> str:
    top = sorted(
        stats.top_findings,
        key=lambda item: (-_severity_rank(item[0]), item[2], item[1]),
    )[:3]
    must = stats.severity_counts.get("high", 0)
    caution = stats.severity_counts.get("medium", 0)
    tips = stats.severity_counts.get("low", 0)
    skipped_reasons = (
        ", ".join(f"{k}={v}" for k, v in sorted(stats.skipped_reasons.items()))
        if stats.skipped_reasons
        else "none"
    )

    is_japanese = settings.review_language == "ja"
    lines = (
        [
            "## レビューサマリー",
            f"- 変更ファイル数: {total_files}",
            f"- レビュー対象数: {stats.reviewed_count}",
            f"- 指摘件数: {stats.findings_total} (must={must}, caution={caution}, tips={tips})",
            f"- 未レビュー理由: {skipped_reasons}",
            "",
            "### 重要指摘 Top 3",
        ]
        if is_japanese
        else [
            "## Review Summary",
            f"- changed_files: {total_files}",
            f"- reviewed_files: {stats.reviewed_count}",
            f"- findings: {stats.findings_total} (must={must}, caution={caution}, tips={tips})",
            f"- skipped_reasons: {skipped_reasons}",
            "",
            "### Top 3 Findings",
        ]
    )
    if not top:
        lines.append("- なし" if is_japanese else "- none")
    else:
        for severity, line, path, body in top:
            masked = _mask_sensitive_text(body).replace("\n", " ").strip()
            lines.append(f"- [{severity}] {path}:{line} - {masked}")

    limited_lines = lines[: settings.summary_max_lines]
    summary = "\n".join(limited_lines).strip()
    if len(summary) > settings.summary_max_chars:
        summary = f"{summary[: settings.summary_max_chars].rstrip()}\n\n[truncated]"
    return summary


def main() -> int:
    args = parse_args()

    try:
        settings = load_settings(config_path=args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    effective_dry_run = settings.dry_run or args.dry_run
    effective_fail_fast = settings.fail_fast or args.fail_fast

    _configure_logging(settings)

    repo_root = Path(args.repo_root).resolve()
    rules_file = _resolve_optional_file(repo_root, args.rules_file, "rules.md")
    reviewignore_file = _resolve_optional_file(repo_root, args.reviewignore_file, ".reviewignore")
    rules_text = load_rules(
        repo_root=rules_file.parent,
        filename=rules_file.name,
    )
    ignore = ReviewIgnore.from_file(
        repo_root=reviewignore_file.parent,
        filename=reviewignore_file.name,
    )

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
    post_inline = _should_post_inline(settings)
    post_summary = _should_post_summary(settings)

    for file in files:
        should_review, reason = should_review_file(file, ignore, settings)
        if not should_review:
            stats.skipped_count += 1
            stats.skipped_reasons[reason] += 1
            logging.info("Skip %s: %s", file.path, reason)
            continue

        stats.reviewed_count += 1
        try:
            posted_delta, skipped_delta, emitted_comments = _review_single_file(
                file=file,
                client=client,
                reviewer=reviewer,
                rules_text=rules_text,
                existing_positions=existing_positions,
                diff_refs=diff_refs,
                effective_dry_run=effective_dry_run,
                allow_inline_post=post_inline,
            )
            _record_summary_candidates(stats, emitted_comments)
            stats.posted_count += posted_delta
            stats.skipped_count += skipped_delta
        except Exception as exc:  # noqa: BLE001
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                logging.exception("Failed to process %s: %s", file.path, exc)
            else:
                logging.error("Failed to process %s: %s", file.path, exc)
            if effective_fail_fast:
                return 1

    if post_summary:
        summary = _build_summary(stats=stats, total_files=len(files), settings=settings)
        if effective_dry_run:
            logging.info("[DRY-RUN] summary prepared")
        else:
            client.upsert_summary(summary)
            logging.info("Posted summary note")

    print(
        "Review completed: "
        f"total_files={len(files)} reviewed_files={stats.reviewed_count} "
        f"posted={stats.posted_count} skipped={stats.skipped_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
