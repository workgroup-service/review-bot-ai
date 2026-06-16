# @author Cursor
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class ReviewIgnore:
    patterns: list[str]

    @classmethod
    def from_file(cls, repo_root: Path, filename: str = ".reviewignore") -> "ReviewIgnore":
        ignore_file = repo_root / filename
        if not ignore_file.exists():
            return cls(patterns=[])

        patterns: list[str] = []
        for line in ignore_file.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            patterns.append(raw)
        return cls(patterns=patterns)

    def should_ignore(self, relative_path: str) -> bool:
        posix_path = PurePosixPath(relative_path).as_posix()
        file_name = PurePosixPath(relative_path).name
        for pattern in self.patterns:
            if fnmatch(posix_path, pattern) or fnmatch(file_name, pattern):
                return True
        return False
