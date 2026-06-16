# @author Cursor
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import List, Optional

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError
from pydantic import BaseModel, Field, ValidationError


class ReviewFindingSchema(BaseModel):
    line: int = Field(description="Line number in the new file")
    severity: str = Field(description="high | medium | low")
    comment: str = Field(description="Why this is an issue")
    suggestion: Optional[str] = Field(default=None, description="Replacement code only, optional")


class ReviewResponseSchema(BaseModel):
    findings: List[ReviewFindingSchema] = Field(default_factory=list)


@dataclass(frozen=True)
class ReviewFinding:
    line: int
    severity: str
    comment: str
    suggestion: Optional[str] = None


class LLMReviewer:
    def __init__(self, model_name: str, api_key: str, review_language: str = "ja") -> None:
        self._client = OpenAI(api_key=api_key)
        self._model_name = model_name
        self._review_language = "en" if review_language == "en" else "ja"

    def review_diff(self, path: str, diff: str, rules_text: str) -> List[ReviewFinding]:
        system_prompt = (
            "You are an elite code reviewer for merge requests. "
            "Focus only on actionable issues in: bugs, performance (especially N+1), "
            "security risks, and violations of project rules. "
            "Do not invent context not present in the diff. "
            "Return no findings if there is no clear issue."
        )
        system_prompt += (
            "\nSeverity rubric (strict):\n"
            "- high: must-fix issues such as security risks, data corruption/loss, crashes, "
            "auth/permission flaws, privacy leaks, and explicit must-not violations in rules.\n"
            "- medium: likely bug risks, notable performance regressions (including probable N+1), "
            "and correctness concerns that may break behavior.\n"
            "- low: optional improvements or readability/maintainability suggestions with low risk.\n"
            "If uncertain between two levels, choose the more severe one."
        )
        system_prompt += (
            "\nWrite all review comments in English."
            if self._review_language == "en"
            else "\nWrite all review comments in Japanese."
        )

        compact_rules = _truncate_text(rules_text.strip(), max_chars=12000)
        if compact_rules:
            system_prompt += f"\n\nProject rules:\n{_mask_sensitive_text(compact_rules)}"

        findings: List[ReviewFinding] = []
        for chunk in _split_diff_into_chunks(diff, max_chunk_chars=14000):
            human_prompt = (
                f"File path: {path}\n"
                "Review the unified diff below. "
                "Use line numbers from the new file side.\n\n"
                f"{_mask_sensitive_text(chunk)}\n\n"
                "Return only valid JSON with this exact shape:\n"
                '{\n'
                '  "findings": [\n'
                "    {\n"
                '      "line": 123,\n'
                '      "severity": "high|medium|low",\n'
                '      "comment": "issue explanation",\n'
                '      "suggestion": "optional replacement code or null"\n'
                "    }\n"
                "  ]\n"
                "}\n"
                "If there are no issues, return: {\"findings\": []}."
            )

            try:
                raw_text = _invoke_with_retry(
                    self._client,
                    self._model_name,
                    f"{system_prompt}\n\n{human_prompt}",
                )
                response = _parse_review_response(raw_text)
            except Exception as exc:  # noqa: BLE001
                logging.error("LLM chunk failed for %s: %s", path, exc)
                continue
            for item in response.findings:
                if item.line <= 0:
                    continue
                severity = _normalize_severity(
                    raw_severity=item.severity,
                    comment=item.comment,
                    suggestion=item.suggestion,
                )
                findings.append(
                    ReviewFinding(
                        line=item.line,
                        severity=severity,
                        comment=item.comment.strip(),
                        suggestion=item.suggestion,
                    )
                )

        return _dedupe_findings(findings)


def _parse_review_response(raw_text: str) -> ReviewResponseSchema:
    raw = raw_text.strip()

    if "```" in raw:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]

    try:
        payload = json.loads(raw)
        return ReviewResponseSchema.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"Failed to parse LLM review output as JSON: {raw_text}") from exc


def _invoke_with_retry(client: OpenAI, model_name: str, prompt: str, max_retries: int = 4) -> str:
    for attempt in range(1, max_retries + 1):
        try:
            response = client.responses.create(
                model=model_name,
                input=prompt,
                max_output_tokens=1500,
            )
            return (response.output_text or "").strip()
        except (InternalServerError, RateLimitError, APITimeoutError, APIConnectionError) as exc:
            if attempt == max_retries:
                raise
            sleep_s = min(2**attempt, 12)
            logging.warning(
                "LLM request failed (attempt %s/%s): %s. Retrying in %ss.",
                attempt,
                max_retries,
                exc,
                sleep_s,
            )
            time.sleep(sleep_s)
    raise RuntimeError("Unexpected retry loop exit")


def _split_diff_into_chunks(diff: str, max_chunk_chars: int) -> List[str]:
    hunks: List[str] = []
    current: List[str] = []
    for line in diff.splitlines():
        if line.startswith("@@") and current:
            hunks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        hunks.append("\n".join(current))

    chunks: List[str] = []
    chunk = ""
    for hunk in hunks:
        if len(hunk) > max_chunk_chars:
            for i in range(0, len(hunk), max_chunk_chars):
                part = hunk[i : i + max_chunk_chars]
                if part.strip():
                    chunks.append(part)
            continue

        if not chunk:
            chunk = hunk
            continue

        if len(chunk) + 2 + len(hunk) <= max_chunk_chars:
            chunk = f"{chunk}\n\n{hunk}"
        else:
            chunks.append(chunk)
            chunk = hunk

    if chunk:
        chunks.append(chunk)

    return chunks or [diff]


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n\n[truncated]"


def _dedupe_findings(findings: List[ReviewFinding]) -> List[ReviewFinding]:
    seen: set[tuple[int, str]] = set()
    unique: List[ReviewFinding] = []
    for finding in findings:
        key = (finding.line, finding.comment)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def _normalize_severity(raw_severity: str, comment: str, suggestion: Optional[str]) -> str:
    severity = raw_severity.lower().strip()
    if severity not in {"high", "medium", "low"}:
        severity = "medium"

    text = comment.lower()
    must_fix_keywords = (
        "security",
        "vulnerability",
        "auth",
        "permission",
        "credential",
        "secret",
        "token",
        "password",
        "privacy",
        "pii",
        "leak",
        "injection",
        "xss",
        "sql injection",
        "crash",
        "panic",
        "fatal",
        "data loss",
        "corruption",
    )
    caution_keywords = (
        "n+1",
        "performance",
        "inefficient",
        "regression",
        "race condition",
        "deadlock",
        "null",
        "out of bounds",
    )

    if any(word in text for word in must_fix_keywords):
        return "high"
    if severity == "low" and any(word in text for word in caution_keywords):
        return "medium"
    if severity == "low" and not suggestion:
        return "medium"
    return severity


def _mask_sensitive_text(text: str) -> str:
    masked = text
    patterns = [
        # Key/value style secrets.
        (
            re.compile(
                r"(?i)\b(api[_-]?key|secret|token|password|passwd|authorization)\b"
                r"(\s*[:=]\s*)([\"']?)[^\"'\s]{6,}([\"']?)"
            ),
            r"\1\2\3[REDACTED]\4",
        ),
        # Bearer tokens.
        (
            re.compile(r"(?i)\b(bearer\s+)[a-z0-9\-._~+/]+=*"),
            r"\1[REDACTED]",
        ),
        # OpenAI-like keys and common token prefixes.
        (
            re.compile(r"\b(sk|glpat|ghp|github_pat)_[A-Za-z0-9_\-]{8,}\b"),
            "[REDACTED_TOKEN]",
        ),
        # JWT-like strings.
        (
            re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9._-]{10,}\.[A-Za-z0-9._-]{10,}\b"),
            "[REDACTED_JWT]",
        ),
        # Private key blocks.
        (
            re.compile(
                r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
            ),
            "-----BEGIN PRIVATE KEY-----\n[REDACTED]\n-----END PRIVATE KEY-----",
        ),
    ]

    for pattern, replacement in patterns:
        masked = pattern.sub(replacement, masked)
    return masked
