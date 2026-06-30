#!/usr/bin/env python3
"""Platform detection for recall.

Detects the current AI coding platform so scripts can adapt path
conventions and session file formats accordingly.
"""

import os
from pathlib import Path
from enum import Enum


class Platform(str, Enum):
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
    GEMINI_CLI = "gemini-cli"
    UNKNOWN = "unknown"


def detect_platform() -> Platform:
    """Detect platform from injected environment variables."""
    # Claude Code injects CLAUDE_* vars
    if os.environ.get("CLAUDE_CODE_VERSION") or os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return Platform.CLAUDE_CODE

    # OpenAI Codex CLI
    if os.environ.get("CODEX_VERSION") or os.environ.get("CODEX_SESSION_ID") or os.environ.get("CODEX_PROJECT"):
        return Platform.CODEX

    # Gemini CLI
    if os.environ.get("GEMINI_CLI_VERSION") or os.environ.get("GEMINI_SESSION_ID"):
        return Platform.GEMINI_CLI

    return Platform.UNKNOWN


def get_sessions_dir(platform: Platform = None) -> Path:
    """Return the directory where the platform writes session files."""
    if platform is None:
        platform = detect_platform()

    if platform == Platform.CLAUDE_CODE:
        return Path.home() / ".claude" / "projects"
    elif platform == Platform.CODEX:
        return Path.home() / ".codex" / "sessions"
    elif platform == Platform.GEMINI_CLI:
        return Path.home() / ".gemini" / "sessions"
    else:
        return Path.home() / ".claude" / "projects"  # safest fallback
