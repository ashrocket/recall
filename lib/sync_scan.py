"""
Secret scanning for sync push.
Scans YAML files for common secret patterns before pushing to remote.
"""

import re
from pathlib import Path
from typing import List

SECRET_PATTERNS = [
    ("AWS access key", r"AKIA[0-9A-Z]{16}"),
    ("API token (sk-)", r"sk-[a-zA-Z0-9_-]{20,}"),
    ("GitHub token", r"ghp_[a-zA-Z0-9]{20,}"),
    ("GitLab token", r"glpat-[a-zA-Z0-9_-]{20,}"),
    ("Bearer token", r"Bearer\s+[a-zA-Z0-9._-]{20,}"),
    ("Connection string", r"(?:postgres|mongodb|mysql|redis)://[^\s]+:[^\s]+@"),
    ("Password field", r"(?:password|passwd|secret)\s*[=:]\s*\S{8,}"),
    ("Private key", r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"),
]

_compiled = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in SECRET_PATTERNS]


def scan_for_secrets(content: str) -> List[dict]:
    findings = []
    for line_num, line in enumerate(content.splitlines(), 1):
        for name, regex in _compiled:
            if regex.search(line):
                findings.append({
                    "type": name,
                    "line": line_num,
                    "preview": line.strip()[:80],
                })
    return findings


def scan_file(file_path: Path) -> List[dict]:
    try:
        content = file_path.read_text(errors="replace")
    except IOError:
        return []
    findings = scan_for_secrets(content)
    for f in findings:
        f["file"] = str(file_path)
    return findings


def scan_directory(dir_path: Path, glob: str = "*.yaml") -> List[dict]:
    all_findings = []
    for f in dir_path.rglob(glob):
        all_findings.extend(scan_file(f))
    return all_findings
