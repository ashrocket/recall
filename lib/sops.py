#!/usr/bin/env python3
"""
SOP loading and matching library.
Handles layered SOPs (global + per-project).
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

GLOBAL_SOPS_PATH = Path.home() / ".claude" / "shell-failures" / "sops.json"
PROJECT_SOPS_NAME = ".claude/sops.json"


def get_project_sops_path() -> Optional[Path]:
    """Find project sops.json by walking up from cwd."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / PROJECT_SOPS_NAME
        if candidate.exists():
            return candidate
    return None


def load_sops() -> dict:
    """Load and merge SOPs (project overrides global)."""
    sops = {"version": 1, "sops": {}}

    # Load global
    if GLOBAL_SOPS_PATH.exists():
        try:
            with open(GLOBAL_SOPS_PATH) as f:
                global_data = json.load(f)
                sops["sops"].update(global_data.get("sops", {}))
        except (json.JSONDecodeError, IOError):
            pass

    # Load project (overrides global)
    project_path = get_project_sops_path()
    if project_path:
        try:
            with open(project_path) as f:
                project_data = json.load(f)
                sops["sops"].update(project_data.get("sops", {}))
        except (json.JSONDecodeError, IOError):
            pass

    return sops


def match_error(error_msg: str, sops: dict) -> Optional[tuple[str, dict]]:
    """Match error message against SOP patterns. Returns (name, sop) or None."""
    error_lower = error_msg.lower()

    for name, sop in sops.get("sops", {}).items():
        patterns = sop.get("patterns", [])
        for pattern in patterns:
            if pattern.lower() in error_lower:
                return (name, sop)

    return None


def format_sop(name: str, sop: dict) -> str:
    """Format SOP for display."""
    lines = [
        f"SOP: {name}",
        f"  {sop.get('description', '')}",
        "",
        "  Fixes:"
    ]
    for fix in sop.get("fixes", []):
        lines.append(f"    - {fix}")

    examples = sop.get("examples", {})
    if examples.get("bad") or examples.get("good"):
        lines.append("")
        if examples.get("bad"):
            lines.append(f"  BAD:  {examples['bad']}")
        if examples.get("good"):
            lines.append(f"  GOOD: {examples['good']}")

    return "\n".join(lines)
