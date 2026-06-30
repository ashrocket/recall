#!/usr/bin/env python3
"""Tests for lib/platform.py — platform detection."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.platform import detect_platform, get_sessions_dir, Platform


class TestDetectPlatform:
    def test_detects_claude_code_via_version(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_VERSION", "1.0.0")
        assert detect_platform() == Platform.CLAUDE_CODE

    def test_detects_claude_code_via_project_dir(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/tmp/myproject")
        assert detect_platform() == Platform.CLAUDE_CODE

    def test_detects_claude_code_via_plugin_root(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/home/user/.claude/plugins/recall")
        assert detect_platform() == Platform.CLAUDE_CODE

    def test_detects_codex_via_version(self, monkeypatch):
        monkeypatch.setenv("CODEX_VERSION", "0.1.0")
        assert detect_platform() == Platform.CODEX

    def test_detects_codex_via_session_id(self, monkeypatch):
        monkeypatch.setenv("CODEX_SESSION_ID", "abc-123")
        assert detect_platform() == Platform.CODEX

    def test_detects_codex_via_project(self, monkeypatch):
        monkeypatch.setenv("CODEX_PROJECT", "/tmp/myproject")
        assert detect_platform() == Platform.CODEX

    def test_detects_gemini_via_version(self, monkeypatch):
        monkeypatch.setenv("GEMINI_CLI_VERSION", "1.0")
        assert detect_platform() == Platform.GEMINI_CLI

    def test_detects_gemini_via_session_id(self, monkeypatch):
        monkeypatch.setenv("GEMINI_SESSION_ID", "xyz-456")
        assert detect_platform() == Platform.GEMINI_CLI

    def test_returns_unknown_with_no_vars(self, monkeypatch):
        for var in ["CLAUDE_CODE_VERSION", "CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT",
                    "CODEX_VERSION", "CODEX_SESSION_ID", "CODEX_PROJECT",
                    "GEMINI_CLI_VERSION", "GEMINI_SESSION_ID"]:
            monkeypatch.delenv(var, raising=False)
        assert detect_platform() == Platform.UNKNOWN

    def test_claude_code_takes_precedence(self, monkeypatch):
        """Claude Code vars win when multiple platforms are set."""
        monkeypatch.setenv("CLAUDE_CODE_VERSION", "1.0.0")
        monkeypatch.setenv("CODEX_VERSION", "0.1.0")
        assert detect_platform() == Platform.CLAUDE_CODE


class TestGetSessionsDir:
    def test_claude_code_dir(self):
        d = get_sessions_dir(Platform.CLAUDE_CODE)
        assert str(d).endswith(".claude/projects")

    def test_codex_dir(self):
        d = get_sessions_dir(Platform.CODEX)
        assert str(d).endswith(".codex/sessions")

    def test_gemini_dir(self):
        d = get_sessions_dir(Platform.GEMINI_CLI)
        assert str(d).endswith(".gemini/sessions")

    def test_unknown_falls_back_to_claude(self):
        d = get_sessions_dir(Platform.UNKNOWN)
        assert str(d).endswith(".claude/projects")

    def test_platform_is_enum_string(self):
        """Platform values can be compared to plain strings."""
        assert Platform.CODEX == "codex"
        assert Platform.CLAUDE_CODE == "claude-code"
