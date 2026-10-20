#!/usr/bin/env bash
# @author Cursor
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-$(pwd)}"
CONFIG_FILE="$(mktemp "${TMPDIR:-/tmp}/review-bot-ci.XXXXXX.env")"
trap 'rm -f "${CONFIG_FILE}"' EXIT

PROJECT_ID="${PROJECT_ID:-${CI_PROJECT_ID:-}}"
MR_IID="${MR_IID:-${CI_MERGE_REQUEST_IID:-}}"
GITLAB_URL="${GITLAB_URL:-${CI_SERVER_URL:-https://gitlab.com}}"

if [[ -z "${GITLAB_ALLOWED_HOSTS:-}" ]]; then
  host="${GITLAB_URL#https://}"
  host="${host%%/*}"
  GITLAB_ALLOWED_HOSTS="${host}"
fi

require_var() {
  local key="$1"
  if [[ -z "${!key:-}" ]]; then
    echo "Missing required variable: ${key}" >&2
    exit 2
  fi
}

require_var "GITLAB_TOKEN"
require_var "OPENAI_API_KEY"
require_var "PROJECT_ID"
require_var "MR_IID"

{
  printf 'GITLAB_TOKEN=%s\n' "${GITLAB_TOKEN}"
  printf 'PROJECT_ID=%s\n' "${PROJECT_ID}"
  printf 'MR_IID=%s\n' "${MR_IID}"
  printf 'OPENAI_API_KEY=%s\n' "${OPENAI_API_KEY}"
  printf 'REVIEW_PLATFORM=%s\n' "${REVIEW_PLATFORM:-gitlab}"
  printf 'LLM_PROVIDER=%s\n' "${LLM_PROVIDER:-openai}"
  printf 'GITLAB_URL=%s\n' "${GITLAB_URL}"
  printf 'GITLAB_ALLOWED_HOSTS=%s\n' "${GITLAB_ALLOWED_HOSTS}"
  printf 'LLM_BLOCKED_PATHS=%s\n' "${LLM_BLOCKED_PATHS:-}"
  printf 'MODEL_NAME=%s\n' "${MODEL_NAME:-gpt-5.3-codex}"
  printf 'MAX_FILE_LINES=%s\n' "${MAX_FILE_LINES:-3000}"
  printf 'BOT_USERNAME=%s\n' "${BOT_USERNAME:-review-bot}"
  printf 'BOT_USER_ID=%s\n' "${BOT_USER_ID:-}"
  printf 'LOG_LEVEL=%s\n' "${LOG_LEVEL:-INFO}"
  printf 'FAIL_FAST=%s\n' "${FAIL_FAST:-false}"
  printf 'DRY_RUN=%s\n' "${DRY_RUN:-false}"
  printf 'REVIEW_LANGUAGE=%s\n' "${REVIEW_LANGUAGE:-ja}"
  printf 'OUTPUT_MODE=%s\n' "${OUTPUT_MODE:-inline}"
  printf 'SUMMARY_MAX_LINES=%s\n' "${SUMMARY_MAX_LINES:-30}"
  printf 'SUMMARY_MAX_CHARS=%s\n' "${SUMMARY_MAX_CHARS:-3000}"
} > "${CONFIG_FILE}"

cli_args=(--config "${CONFIG_FILE}" --repo-root "${ROOT_DIR}")

if [[ -n "${RULES_FILE:-}" ]]; then
  cli_args+=(--rules-file "${RULES_FILE}")
fi
if [[ -n "${REVIEWIGNORE_FILE:-}" ]]; then
  cli_args+=(--reviewignore-file "${REVIEWIGNORE_FILE}")
fi

if [[ -n "${REVIEW_BOT_ARGS:-}" ]]; then
  # Space-delimited extra args for main.py (for example: --dry-run --fail-fast)
  read -r -a extra_args <<< "${REVIEW_BOT_ARGS}"
  cli_args+=("${extra_args[@]}")
fi

python "${ROOT_DIR}/main.py" "${cli_args[@]}" "$@"
