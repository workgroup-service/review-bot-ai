# @author Cursor
from __future__ import annotations

import logging
from pathlib import Path


def load_rules(
    repo_root: Path,
    filename: str = "rules.md",
    rules_dirname: str = "rules.d",
) -> str:
    sections: list[str] = []

    rule_file = repo_root / filename
    if rule_file.exists():
        sections.append(rule_file.read_text(encoding="utf-8").strip())
    else:
        logging.warning("%s not found. Continue without extra project rules.", filename)

    rules_dir = repo_root / rules_dirname
    if rules_dir.exists() and rules_dir.is_dir():
        for child in sorted(rules_dir.glob("*.md")):
            content = child.read_text(encoding="utf-8").strip()
            if not content:
                continue
            sections.append(f"## From {child.name}\n{content}")

    return "\n\n".join(section for section in sections if section).strip()
