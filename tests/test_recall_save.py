"""Tests for bin/recall-save.py."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock


def _import_recall_save():
    script = Path(__file__).resolve().parent.parent / "bin" / "recall-save.py"
    spec = importlib.util.spec_from_file_location("recall_save", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["recall_save"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_build_restart_prompt_uses_local_extracts():
    mod = _import_recall_save()
    prompt = mod.build_restart_prompt(
        working_dir="/tmp/app",
        session_id="codex-abc",
        summary_entry={"summary": "Fix checkout redirect"},
        details={
            "summary": "Fix checkout redirect and reduce token use",
            "user_messages": [
                {"content": "ok"},
                {"content": "Fix the checkout redirect in src/auth.ts and verify the browser test"},
            ],
            "commands": [{"command": "pytest tests/test_auth.py"}],
            "failures": [{"command": "pytest", "error": "AssertionError: redirect mismatch"}],
        },
        git_info={
            "branch": "main",
            "status": " M src/auth.ts",
            "log": "abc123 Fix previous auth issue",
        },
    )

    assert "No LLM distillation was used" in prompt
    assert "Fix checkout redirect" in prompt
    assert "`src/auth.ts`" in prompt
    assert "`pytest tests/test_auth.py`" in prompt
    assert "AssertionError" in prompt


def test_extract_paths_deduplicates_paths():
    mod = _import_recall_save()
    paths = mod.extract_paths([
        "Edit src/auth.ts and src/auth.ts",
        "Run tests/test_auth.py",
    ])
    assert paths == ["src/auth.ts", "tests/test_auth.py"]


def test_register_restart_uses_project_relative_prompt_path(tmp_path):
    mod = _import_recall_save()
    project_dir = tmp_path / "proj"
    prompt_path = project_dir / "recall-restarts" / "fix-auth.prompt"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("prompt")
    calls = []

    def fake_run(args, cwd=None, timeout=10):
        calls.append(args)
        return 0, "Saved: fix auth"

    with mock.patch.object(mod, "get_project_dir", return_value=project_dir), \
         mock.patch.object(mod, "run_command", side_effect=fake_run):
        output = mod.register_restart("/tmp/app", "fix auth", prompt_path, "proj", "codex-abc")

    assert output == "Saved: fix auth"
    assert "recall-restarts/fix-auth.prompt" in calls[0]


class TestCmuxGetResumeCheckpoint:
    def test_returns_empty_outside_cmux(self, monkeypatch):
        mod = _import_recall_save()
        monkeypatch.delenv("CMUX_SURFACE_ID", raising=False)
        assert mod.cmux_get_resume_checkpoint() == ""

    def test_returns_empty_when_cmux_missing(self, monkeypatch):
        mod = _import_recall_save()
        monkeypatch.setenv("CMUX_SURFACE_ID", "surf-abc")
        with mock.patch("shutil.which", return_value=None):
            assert mod.cmux_get_resume_checkpoint() == ""

    def test_parses_checkpoint_id_from_json(self, monkeypatch):
        mod = _import_recall_save()
        monkeypatch.setenv("CMUX_SURFACE_ID", "surf-abc")
        payload = json.dumps({
            "resume_binding": {"checkpoint_id": "abc-uuid-123", "command": "claude --resume abc-uuid-123"}
        })
        with mock.patch("shutil.which", return_value="/usr/bin/cmux"), \
             mock.patch.object(mod, "run_command", return_value=(0, payload)):
            assert mod.cmux_get_resume_checkpoint() == "abc-uuid-123"

    def test_returns_empty_on_error(self, monkeypatch):
        mod = _import_recall_save()
        monkeypatch.setenv("CMUX_SURFACE_ID", "surf-abc")
        with mock.patch("shutil.which", return_value="/usr/bin/cmux"), \
             mock.patch.object(mod, "run_command", return_value=(1, "error")):
            assert mod.cmux_get_resume_checkpoint() == ""

    def test_returns_empty_on_corrupt_json(self, monkeypatch):
        mod = _import_recall_save()
        monkeypatch.setenv("CMUX_SURFACE_ID", "surf-abc")
        with mock.patch("shutil.which", return_value="/usr/bin/cmux"), \
             mock.patch.object(mod, "run_command", return_value=(0, "not-json")):
            assert mod.cmux_get_resume_checkpoint() == ""


class TestCmuxRegisterRecall:
    def test_no_op_outside_cmux(self, tmp_path, monkeypatch):
        mod = _import_recall_save()
        monkeypatch.delenv("CMUX_SURFACE_ID", raising=False)
        result = mod.cmux_register_recall("/tmp/app", tmp_path / "prompt.md", "fix auth", "ses-1")
        assert result == ""

    def test_no_op_when_cmux_not_on_path(self, tmp_path, monkeypatch):
        mod = _import_recall_save()
        monkeypatch.setenv("CMUX_SURFACE_ID", "surface-abc")
        with mock.patch("shutil.which", return_value=None):
            result = mod.cmux_register_recall("/tmp/app", tmp_path / "prompt.md", "fix auth", "ses-1")
        assert result == ""

    def test_registers_with_correct_flags(self, tmp_path, monkeypatch):
        mod = _import_recall_save()
        monkeypatch.setenv("CMUX_SURFACE_ID", "surface-abc")
        prompt = tmp_path / "fix-auth.prompt"
        prompt.write_text("context")
        captured = []

        def fake_run(args, cwd=None, timeout=10):
            captured.extend(args)
            return 0, ""

        with mock.patch("shutil.which", return_value="/usr/bin/cmux"), \
             mock.patch.object(mod, "run_command", side_effect=fake_run):
            result = mod.cmux_register_recall("/tmp/app", prompt, "fix auth", "ses-123")

        assert result == "Registered with cmux for recall restore."
        assert "cmux" in captured
        assert "--kind" in captured and captured[captured.index("--kind") + 1] == "claude"
        assert "--source" in captured and captured[captured.index("--source") + 1] == "recall"
        assert "--checkpoint" in captured and captured[captured.index("--checkpoint") + 1] == "ses-123"
        shell_idx = captured.index("--shell")
        assert str(prompt) in captured[shell_idx + 1]
        assert "/tmp/app" in captured[shell_idx + 1]

    def test_omits_checkpoint_when_no_session_id(self, tmp_path, monkeypatch):
        mod = _import_recall_save()
        monkeypatch.setenv("CMUX_SURFACE_ID", "surface-abc")
        captured = []

        def fake_run(args, cwd=None, timeout=10):
            captured.extend(args)
            return 0, ""

        with mock.patch("shutil.which", return_value="/usr/bin/cmux"), \
             mock.patch.object(mod, "run_command", side_effect=fake_run):
            mod.cmux_register_recall("/tmp/app", tmp_path / "p.md", "fix auth", "")

        assert "--checkpoint" not in captured

    def test_reports_failure(self, tmp_path, monkeypatch):
        mod = _import_recall_save()
        monkeypatch.setenv("CMUX_SURFACE_ID", "surface-abc")

        with mock.patch("shutil.which", return_value="/usr/bin/cmux"), \
             mock.patch.object(mod, "run_command", return_value=(1, "surface not found")):
            result = mod.cmux_register_recall("/tmp/app", tmp_path / "p.md", "fix", "")

        assert "cmux registration failed" in result
        assert "surface not found" in result


def test_find_latest_codex_rollout_for_matches_cwd(tmp_path):
    mod = _import_recall_save()
    cwd = tmp_path / "repo"
    cwd.mkdir()
    sessions = tmp_path / ".codex" / "sessions" / "2026" / "05" / "20"
    sessions.mkdir(parents=True)
    rollout = sessions / "rollout-test.jsonl"
    rollout.write_text(json.dumps({
        "type": "session_meta",
        "payload": {"id": "abc", "cwd": str(cwd), "timestamp": "2026-05-20T12:00:00Z"},
    }))

    with mock.patch.object(mod.Path, "home", return_value=tmp_path):
        assert mod.find_latest_codex_rollout_for(str(cwd)) == rollout


def test_index_output_has_current_session_only_for_indexed_or_skipped():
    mod = _import_recall_save()
    assert mod.index_output_has_current_session("Indexed session abc", skipped=False) is True
    assert mod.index_output_has_current_session("No session found", skipped=False) is False
    assert mod.index_output_has_current_session("Indexing skipped.", skipped=True) is True


class TestAutoPlatformDetection:
    """Auto mode must pick the platform with the freshest session evidence,
    not unconditionally prefer Codex when any rollout exists (the bug that
    made /recall save from a live Claude session index a stale Codex rollout)."""

    def _setup(self, tmp_path, codex_age, claude_age):
        """Create a codex rollout and a claude session with given mtimes (epoch)."""
        import os
        cwd = tmp_path / "repo"
        cwd.mkdir(exist_ok=True)
        rollout = None
        if codex_age is not None:
            sessions = tmp_path / ".codex" / "sessions" / "2026" / "06" / "01"
            sessions.mkdir(parents=True, exist_ok=True)
            rollout = sessions / "rollout-test.jsonl"
            rollout.write_text(json.dumps({
                "type": "session_meta",
                "payload": {"id": "abc", "cwd": str(cwd)},
            }))
            os.utime(rollout, (codex_age, codex_age))
        if claude_age is not None:
            claude_dir = tmp_path / ".claude" / "projects" / "-repo"
            claude_dir.mkdir(parents=True, exist_ok=True)
            sess = claude_dir / "live-session.jsonl"
            sess.write_text("{}")
            os.utime(sess, (claude_age, claude_age))
        return cwd, rollout

    def test_auto_prefers_newer_claude_session(self, tmp_path):
        mod = _import_recall_save()
        cwd, rollout = self._setup(tmp_path, codex_age=1_000_000, claude_age=2_000_000)
        with mock.patch.object(mod.Path, "home", return_value=tmp_path), \
             mock.patch.object(mod, "get_project_folders", return_value=("-repo", "-repo")):
            platform, found = mod.detect_auto_platform(str(cwd))
        assert platform == "claude"
        assert found is None

    def test_auto_prefers_newer_codex_rollout(self, tmp_path):
        mod = _import_recall_save()
        cwd, rollout = self._setup(tmp_path, codex_age=2_000_000, claude_age=1_000_000)
        with mock.patch.object(mod.Path, "home", return_value=tmp_path), \
             mock.patch.object(mod, "get_project_folders", return_value=("-repo", "-repo")):
            platform, found = mod.detect_auto_platform(str(cwd))
        assert platform == "codex"
        assert found == rollout

    def test_auto_claude_when_no_codex_rollout(self, tmp_path):
        mod = _import_recall_save()
        cwd, _ = self._setup(tmp_path, codex_age=None, claude_age=1_000_000)
        with mock.patch.object(mod.Path, "home", return_value=tmp_path), \
             mock.patch.object(mod, "get_project_folders", return_value=("-repo", "-repo")):
            platform, found = mod.detect_auto_platform(str(cwd))
        assert platform == "claude"
        assert found is None

    def test_auto_codex_when_no_claude_sessions(self, tmp_path):
        mod = _import_recall_save()
        cwd, rollout = self._setup(tmp_path, codex_age=1_000_000, claude_age=None)
        with mock.patch.object(mod.Path, "home", return_value=tmp_path), \
             mock.patch.object(mod, "get_project_folders", return_value=("-repo", "-repo")):
            platform, found = mod.detect_auto_platform(str(cwd))
        assert platform == "codex"
        assert found == rollout

    def test_registration_platform_auto_follows_detection(self, tmp_path):
        mod = _import_recall_save()
        cwd, _ = self._setup(tmp_path, codex_age=1_000_000, claude_age=2_000_000)
        with mock.patch.object(mod.Path, "home", return_value=tmp_path), \
             mock.patch.object(mod, "get_project_folders", return_value=("-repo", "-repo")):
            assert mod.registration_platform(str(cwd), "auto") == "claude"

    def test_agent_jsonl_files_ignored_for_claude_recency(self, tmp_path):
        import os
        mod = _import_recall_save()
        cwd, rollout = self._setup(tmp_path, codex_age=2_000_000, claude_age=1_000_000)
        # an agent- transcript newer than the rollout must NOT flip detection
        agent = tmp_path / ".claude" / "projects" / "-repo" / "agent-xyz.jsonl"
        agent.write_text("{}")
        os.utime(agent, (3_000_000, 3_000_000))
        with mock.patch.object(mod.Path, "home", return_value=tmp_path), \
             mock.patch.object(mod, "get_project_folders", return_value=("-repo", "-repo")):
            platform, _ = mod.detect_auto_platform(str(cwd))
        assert platform == "codex"


class TestFindCurrentClaudeTranscript:
    def test_returns_newest_non_agent_jsonl(self, tmp_path):
        import os
        mod = _import_recall_save()
        proj = tmp_path / ".claude" / "projects" / "myapp"
        proj.mkdir(parents=True)
        old = proj / "old.jsonl"
        new = proj / "new.jsonl"
        old.write_text("{}\n")
        new.write_text("{}\n")
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))
        with mock.patch.object(mod.Path, "home", return_value=tmp_path), \
             mock.patch.object(mod, "get_project_folders", return_value=("myapp", "myapp")):
            assert mod.find_current_claude_transcript("/tmp/myapp") == new

    def test_excludes_agent_transcripts(self, tmp_path):
        import os
        mod = _import_recall_save()
        proj = tmp_path / ".claude" / "projects" / "myapp"
        proj.mkdir(parents=True)
        agent = proj / "agent-sub.jsonl"
        real = proj / "real.jsonl"
        agent.write_text("{}\n")
        real.write_text("{}\n")
        os.utime(agent, (3000, 3000))  # agent is newer but must be skipped
        os.utime(real, (2000, 2000))
        with mock.patch.object(mod.Path, "home", return_value=tmp_path), \
             mock.patch.object(mod, "get_project_folders", return_value=("myapp", "myapp")):
            assert mod.find_current_claude_transcript("/tmp/myapp") == real

    def test_returns_none_when_no_transcripts(self, tmp_path):
        mod = _import_recall_save()
        with mock.patch.object(mod.Path, "home", return_value=tmp_path), \
             mock.patch.object(mod, "get_project_folders", return_value=("missing", "missing")):
            assert mod.find_current_claude_transcript("/tmp/missing") is None


class TestResolveRestartName:
    def test_explicit_name_wins(self, tmp_path):
        mod = _import_recall_save()
        t = tmp_path / "s.jsonl"
        t.write_text('{"type":"custom-title","customTitle":"from-title"}\n')
        assert mod.resolve_restart_name("explicit", "claude", t) == "explicit"

    def test_uses_custom_title_when_no_explicit(self, tmp_path):
        mod = _import_recall_save()
        t = tmp_path / "s.jsonl"
        t.write_text('{"type":"custom-title","customTitle":"from-title"}\n')
        assert mod.resolve_restart_name("", "claude", t) == "from-title"

    def test_empty_when_codex(self, tmp_path):
        mod = _import_recall_save()
        t = tmp_path / "s.jsonl"
        t.write_text('{"type":"custom-title","customTitle":"from-title"}\n')
        assert mod.resolve_restart_name("", "codex", t) == ""

    def test_empty_when_no_title_and_no_explicit(self, tmp_path):
        mod = _import_recall_save()
        t = tmp_path / "s.jsonl"
        t.write_text('{"type":"user","content":"hi"}\n')
        assert mod.resolve_restart_name("", "claude", t) == ""


def test_register_restart_passes_name_when_set(tmp_path):
    mod = _import_recall_save()
    prompt_path = tmp_path / "recall-restarts" / "x.prompt"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("p")
    calls = []

    def fake_run(args, cwd=None, timeout=10):
        calls.append(args)
        return 0, "Saved"

    with mock.patch.object(mod, "get_project_dir", return_value=tmp_path), \
         mock.patch.object(mod, "run_command", side_effect=fake_run):
        mod.register_restart("/tmp/app", "sum", prompt_path, "proj", "sid",
                             name="My Session")
    assert "--name" in calls[0]
    assert "My Session" in calls[0]


def test_register_restart_omits_name_when_empty(tmp_path):
    mod = _import_recall_save()
    prompt_path = tmp_path / "recall-restarts" / "x.prompt"
    prompt_path.parent.mkdir(parents=True)
    prompt_path.write_text("p")
    calls = []

    with mock.patch.object(mod, "get_project_dir", return_value=tmp_path), \
         mock.patch.object(mod, "run_command", side_effect=lambda a, cwd=None, timeout=10: (calls.append(a) or (0, "Saved"))):
        mod.register_restart("/tmp/app", "sum", prompt_path, "proj", "sid", name="")
    assert "--name" not in calls[0]
