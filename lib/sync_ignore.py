"""
.recallignore parser.
Follows gitignore-style patterns (fnmatch). Loaded from sync repo root.
"""

import fnmatch
from pathlib import Path
from typing import List

def load_ignore_patterns(ignore_path: Path) -> List[str]:
    if not ignore_path.exists():
        return []
    patterns = []
    for line in ignore_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns

def should_ignore(file_path: str, patterns: List[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(file_path, pattern):
            return True
    return False
