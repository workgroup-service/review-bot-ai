# @author Cursor
from __future__ import annotations

import logging
from pathlib import Path


def load_rules(repo_root: Path, filename: str = "rules.md") -> str:
    rule_file = repo_root / filename
    if not rule_file.exists():
        logging.warning("%s not found. Continue without extra project rules.", filename)
        return ""
    return rule_file.read_text(encoding="utf-8").strip()
