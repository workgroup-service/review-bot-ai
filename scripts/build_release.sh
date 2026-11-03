#!/usr/bin/env bash
# @author Cursor
# Build a local production app bundle from the current checkout.
# macOS output: dist/review-bot.app
# Other platforms: dist/review-bot/
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -x "${ROOT_DIR}/venv/bin/python" ]]; then
  PYTHON="${PYTHON:-${ROOT_DIR}/venv/bin/python}"
else
  PYTHON="${PYTHON:-python3}"
fi

"${PYTHON}" -m pip install -r requirements.txt pyinstaller
"${PYTHON}" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name review-bot \
  --paths "${ROOT_DIR}" \
  gui.py

if [[ -d "${ROOT_DIR}/dist/review-bot.app" ]]; then
  echo "Built: ${ROOT_DIR}/dist/review-bot.app"
else
  echo "Built: ${ROOT_DIR}/dist/review-bot"
fi
