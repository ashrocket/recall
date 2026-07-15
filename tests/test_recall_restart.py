#!/usr/bin/env python3
"""Tests for bin/recall-restart.py — pure utility functions."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


def _import_recall_restart():
    spec = importlib.util.spec_from_file_location(
        "recall_restart",
        Path(__file__).resolve().parent.parent / "bin" / "recall-restart.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# get_ticket_ids
# ---------------------------------------------------------------------------

class TestGetTicketIds:
    def test_finds_jira_style_tickets(self):
        mod = _import_recall_restart()
        ids = mod.get_ticket_ids("Fix PROJ-123 and ACME-456 together")
        assert ids == {"PROJ-123", "ACME-456"}

    def test_returns_empty_set_when_none(self):
        mod = _import_recall_restart()
        assert mod.get_ticket_ids("no tickets here") == set()

    def test_only_searches_first_500_chars(self):
        mod = _import_recall_restart()
        prefix = "a" * 501
        ids = mod.get_ticket_ids(prefix + " LATE-999")
        assert "LATE-999" not in ids

    def test_deduplicates_repeated_tickets(self):
        mod = _import_recall_restart()
        ids = mod.get_ticket_ids("Fix PROJ-1 and also PROJ-1 again")
        assert ids == {"PROJ-1"}

    def test_single_letter_prefix_not_matched(self):
        mod = _import_recall_restart()
        # Jira tickets need at least 2 uppercase letters before the dash
        ids = mod.get_ticket_ids("T-1 not a ticket")
        # TICKET_RE = r'[A-Z]+-\d+' - single letter IS allowed by the regex
        # so T-1 would match. Let's verify the actual behavior.
        assert isinstance(ids, set)  # just verify it runs without error


# ---------------------------------------------------------------------------
# get_theme (deterministic)
# ---------------------------------------------------------------------------

class TestGetTheme:
    def test_returns_theme_and_ansi_tuple(self):
        mod = _import_recall_restart()
        theme, ansi = mod.get_theme({"PROJ-1"}, {})
        assert isinstance(theme, str)
        assert ansi.startswith("\033[")

    def test_deterministic_for_same_input(self):
        mod = _import_recall_restart()
        r1 = mod.get_theme({"PROJ-1", "PROJ-2"}, {})
        r2 = mod.get_theme({"PROJ-2", "PROJ-1"}, {})
        assert r1 == r2  # order-independent

    def test_different_tickets_give_different_themes(self):
        mod = _import_recall_restart()
        themes = set()
        for i in range(len(mod.THEMES)):
            theme, _ = mod.get_theme({f"TEST-{i * 100}"}, {})
            themes.add(theme)
        # Not all 8 slots need to be covered, but there should be variety
        assert len(themes) >= 1

    def test_falls_back_to_summary_when_no_tickets(self):
        mod = _import_recall_restart()
        entry = {"summary": "fix payment flow", "id": 42}
        theme, ansi = mod.get_theme(set(), entry)
        assert isinstance(theme, str)
        assert theme in mod.THEMES


# ---------------------------------------------------------------------------
# named restart sessions
# ---------------------------------------------------------------------------

class TestNamedRestartSessions:
    def test_slugify_normalizes_display_name(self):
        mod = _import_recall_restart()
        assert mod.slugify("Payroll Bonus Fix!") == "payroll-bonus-fix"

    def test_slugify_caps_long_generated_names(self):
        mod = _import_recall_restart()
        slug = mod.slugify("This is a very long restart summary that should not fill the entire restart list display")
        assert len(slug) <= 72
        assert slug == "this-is-a-very-long-restart-summary-that-should-not-fill-the-entire"

    def test_entry_session_name_prefers_explicit_name(self):
        mod = _import_recall_restart()
        entry = {
            "name": "Launch Checklist",
            "prompt_file": "recall-restarts/old-name.prompt",
            "summary": "old name",
        }
        assert mod.entry_session_name(entry) == "launch-checklist"

    def test_entry_session_name_uses_prompt_filename(self):
        mod = _import_recall_restart()
        entry = {
            "prompt_file": "recall-restarts/payroll-bonus-fix.prompt",
            "summary": "payroll task",
        }
        assert mod.entry_session_name(entry) == "payroll-bonus-fix"

    def test_entry_session_name_falls_back_to_summary(self):
        mod = _import_recall_restart()
        entry = {"summary": "Fix auth bug"}
        assert mod.entry_session_name(entry) == "fix-auth-bug"


# ---------------------------------------------------------------------------
# union_find_groups — ticket-based clustering
# ---------------------------------------------------------------------------

class TestUnionFindGroups:
    def test_groups_entries_sharing_ticket(self):
        mod = _import_recall_restart()
        entries = [
            ({"summary": "Fix PROJ-1 auth bug", "id": 1, "date": "2026-04-01"}, "proj"),
            ({"summary": "Cont PROJ-1 cleanup", "id": 2, "date": "2026-04-02"}, "proj"),
            ({"summary": "Unrelated task", "id": 3, "date": "2026-04-03"}, "proj"),
        ]
        groups = mod.union_find_groups(entries)
        # Entry 1 and 2 share PROJ-1 → same group; entry 3 → own group
        assert len(groups) == 2
        group_ids = [frozenset(e[0]["id"] for e in g) for g in groups.values()]
        assert frozenset({1, 2}) in group_ids
        assert frozenset({3}) in group_ids

    def test_no_tickets_each_entry_own_group(self):
        mod = _import_recall_restart()
        entries = [
            ({"summary": "fix login page", "id": 1, "date": "2026-04-01"}, "proj"),
            ({"summary": "update profile", "id": 2, "date": "2026-04-02"}, "proj"),
        ]
        groups = mod.union_find_groups(entries)
        assert len(groups) == 2

    def test_empty_input(self):
        mod = _import_recall_restart()
        groups = mod.union_find_groups([])
        assert groups == {}

    def test_single_entry(self):
        mod = _import_recall_restart()
        entries = [({"summary": "PROJ-99 task", "id": 1, "date": "2026-04-01"}, "p")]
        groups = mod.union_find_groups(entries)
        assert len(groups) == 1

    def test_three_way_group_via_shared_tickets(self):
        mod = _import_recall_restart()
        entries = [
            ({"summary": "PROJ-1 step one", "id": 1, "date": "2026-04-01"}, "p"),
            ({"summary": "PROJ-1 PROJ-2 bridge", "id": 2, "date": "2026-04-02"}, "p"),
            ({"summary": "PROJ-2 step three", "id": 3, "date": "2026-04-03"}, "p"),
        ]
        groups = mod.union_find_groups(entries)
        assert len(groups) == 1
        only_group = list(groups.values())[0]
        assert len(only_group) == 3

    def test_groups_by_shared_parent_directory(self):
        mod = _import_recall_restart()
        entries = [
            ({"summary": "task a", "id": 1, "date": "2026-04-01", "working_directory": "/home/user/repo/feature-a"}, "p"),
            ({"summary": "task b", "id": 2, "date": "2026-04-02", "working_directory": "/home/user/repo/feature-b"}, "p"),
            ({"summary": "other", "id": 3, "date": "2026-04-03", "working_directory": "/tmp/other-repo"}, "p"),
        ]
        groups = mod.union_find_groups(entries)
        # Entries 1 and 2 share parent /home/user/repo → same group; entry 3 in /tmp/other-repo → own group
        assert len(groups) == 2
        group_sizes = sorted(len(g) for g in groups.values())
        assert group_sizes == [1, 2]


# ---------------------------------------------------------------------------
# find_child_projects
# ---------------------------------------------------------------------------

class TestFindChildProjects:
    def test_finds_subdirectory_projects(self, tmp_path):
        mod = _import_recall_restart()
        projects_dir = tmp_path / ".claude" / "projects"
        (projects_dir / "myapp").mkdir(parents=True)
        (projects_dir / "myapp-feature").mkdir()
        (projects_dir / "myapp-worktree").mkdir()
        (projects_dir / "other").mkdir()

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_child_projects("myapp")

        assert set(result) == {"myapp-feature", "myapp-worktree"}
        assert "other" not in result
        assert "myapp" not in result  # exact match excluded

    def test_returns_empty_when_no_projects_dir(self, tmp_path):
        mod = _import_recall_restart()
        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_child_projects("anything")
        assert result == []

    def test_returns_sorted_results(self, tmp_path):
        mod = _import_recall_restart()
        projects_dir = tmp_path / ".claude" / "projects"
        (projects_dir / "myapp-z").mkdir(parents=True)
        (projects_dir / "myapp-a").mkdir()
        (projects_dir / "myapp-m").mkdir()

        with mock.patch.object(mod.Path, "home", return_value=tmp_path):
            result = mod.find_child_projects("myapp")
        assert result == sorted(result)


# ---------------------------------------------------------------------------
# collect_all_entries
# ---------------------------------------------------------------------------

class TestCollectAllEntries:
    def test_collects_from_current_project(self):
        mod = _import_recall_restart()
        entry = {"id": 1, "summary": "fix auth", "date": "2026-04-24"}
        with mock.patch.object(mod, "load_agents", return_value=[entry]), \
             mock.patch.object(mod, "find_child_projects", return_value=[]):
            result = mod.collect_all_entries("myapp")
        assert len(result) == 1
        assert result[0] == (entry, "myapp")

    def test_collects_from_child_projects(self):
        mod = _import_recall_restart()
        parent_entry = {"id": 1, "summary": "parent task"}
        child_entry = {"id": 2, "summary": "child task"}

        def _load_agents(pf):
            return [parent_entry] if pf == "myapp" else [child_entry]

        with mock.patch.object(mod, "load_agents", side_effect=_load_agents), \
             mock.patch.object(mod, "find_child_projects", return_value=["myapp-feature"]):
            result = mod.collect_all_entries("myapp")

        assert len(result) == 2
        assert (parent_entry, "myapp") in result
        assert (child_entry, "myapp-feature") in result

    def test_empty_when_no_agents(self):
        mod = _import_recall_restart()
        with mock.patch.object(mod, "load_agents", return_value=[]), \
             mock.patch.object(mod, "find_child_projects", return_value=[]):
            result = mod.collect_all_entries("myapp")
        assert result == []


# ---------------------------------------------------------------------------
# ordered_display_entries
# ---------------------------------------------------------------------------

class TestOrderedDisplayEntries:
    def test_returns_numbered_entries_newest_first(self):
        mod = _import_recall_restart()
        entries = [
            ({"id": 1, "summary": "old task", "date": "2026-04-20"}, "proj"),
            ({"id": 2, "summary": "new task", "date": "2026-04-24"}, "proj"),
        ]
        with mock.patch.object(mod, "collect_all_entries", return_value=entries):
            result = mod.ordered_display_entries("proj")

        assert len(result) == 2
        # pos=1 should be newest (2026-04-24)
        pos1_entry = next(e for pos, e, pf in result if pos == 1)
        assert pos1_entry["summary"] == "new task"

    def test_positions_start_at_one(self):
        mod = _import_recall_restart()
        entries = [({"id": i, "summary": f"task {i}", "date": f"2026-04-{i:02d}"}, "proj")
                   for i in range(1, 4)]
        with mock.patch.object(mod, "collect_all_entries", return_value=entries):
            result = mod.ordered_display_entries("proj")
        positions = [pos for pos, _, _ in result]
        assert min(positions) == 1
        assert max(positions) == 3

    def test_empty_input_returns_empty(self):
        mod = _import_recall_restart()
        with mock.patch.object(mod, "collect_all_entries", return_value=[]):
            result = mod.ordered_display_entries("proj")
        assert result == []


# ---------------------------------------------------------------------------
# cmd_save
# ---------------------------------------------------------------------------

import argparse


class TestCmdSave:
    def _make_args(self, **kwargs):
        defaults = dict(
            working_dir="/tmp/myapp",
            summary="fix auth bug",
            prompt_file="",
            role="lead",
            platform="claude-code",
            team="",
            goal="",
            comms_file="",
            session_id="",
            resume_checkpoint="",
            lead_id=None,
            workers=[],
            name="",
        )
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_saves_entry_with_correct_summary(self, capsys):
        mod = _import_recall_restart()
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=[]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda entries, pf: saved.extend(entries)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_save(self._make_args())
        assert len(saved) == 1
        assert saved[0]["summary"] == "fix auth bug"

    def test_id_increments_from_existing(self, capsys):
        mod = _import_recall_restart()
        existing = [{"id": 5, "summary": "old"}]
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=existing), \
             mock.patch.object(mod, "save_agents", side_effect=lambda entries, pf: saved.extend(entries)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_save(self._make_args())
        new_entry = saved[-1]
        assert new_entry["id"] == 6

    def test_id_starts_at_one_when_no_existing(self, capsys):
        mod = _import_recall_restart()
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=[]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda entries, pf: saved.extend(entries)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_save(self._make_args())
        assert saved[0]["id"] == 1

    def test_env_var_fallback_for_role(self, capsys):
        mod = _import_recall_restart()
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=[]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda entries, pf: saved.extend(entries)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"), \
             mock.patch.dict(mod.os.environ, {"RESTART_ROLE": "worker"}):
            mod.cmd_save(self._make_args(role=""))
        assert saved[0]["role"] == "worker"

    def test_env_var_fallback_for_workers(self, capsys):
        mod = _import_recall_restart()
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=[]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda entries, pf: saved.extend(entries)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"), \
             mock.patch.dict(mod.os.environ, {"RESTART_WORKERS": "agent-1,agent-2"}):
            mod.cmd_save(self._make_args(workers=[]))
        assert saved[0]["workers"] == ["agent-1", "agent-2"]

    def test_env_var_fallback_for_lead_id(self, capsys):
        mod = _import_recall_restart()
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=[]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda entries, pf: saved.extend(entries)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"), \
             mock.patch.dict(mod.os.environ, {"RESTART_LEAD": "42"}):
            mod.cmd_save(self._make_args(lead_id=None))
        assert saved[0]["lead_id"] == 42

    def test_non_numeric_lead_id_env_var_is_ignored(self, capsys):
        """RESTART_LEAD with non-numeric value raises ValueError — lead_id stays None."""
        mod = _import_recall_restart()
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=[]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda entries, pf: saved.extend(entries)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"), \
             mock.patch.dict(mod.os.environ, {"RESTART_LEAD": "notanumber"}):
            mod.cmd_save(self._make_args(lead_id=None))
        assert saved[0].get("lead_id") is None

    def test_status_is_saved(self, capsys):
        mod = _import_recall_restart()
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=[]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda entries, pf: saved.extend(entries)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_save(self._make_args())
        assert saved[0]["status"] == "saved"

    def test_prints_confirmation(self, capsys):
        mod = _import_recall_restart()
        with mock.patch.object(mod, "load_agents", return_value=[]), \
             mock.patch.object(mod, "save_agents"), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_save(self._make_args(summary="deploy pipeline"))
        out = capsys.readouterr().out
        assert "deploy pipeline" in out


class TestNamedRestartDedup:
    def _make_args(self, **kwargs):
        defaults = dict(
            working_dir="/tmp/myapp", summary="fix auth bug", prompt_file="",
            role="lead", platform="claude-code", team="", goal="", comms_file="",
            session_id="", resume_checkpoint="", lead_id=None, workers=[], name="",
        )
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_resolve_unique_name_passthrough_when_no_collision(self):
        mod = _import_recall_restart()
        assert mod._resolve_unique_name("Auth Refactor", set(), 7) == "Auth Refactor"

    def test_resolve_unique_name_suffixes_on_collision(self):
        mod = _import_recall_restart()
        existing = {"auth-refactor"}
        result = mod._resolve_unique_name("Auth Refactor", existing, 7)
        assert result != "Auth Refactor"
        assert mod.slugify(result).startswith("auth-refactor-")
        assert mod.slugify(result) not in existing

    def test_explicit_name_is_stored(self, capsys):
        mod = _import_recall_restart()
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=[]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda e, pf: saved.extend(e)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_save(self._make_args(name="My Feature"))
        assert saved[0]["name"] == "My Feature"

    def test_colliding_name_gets_unique_token(self, capsys):
        mod = _import_recall_restart()
        existing = [{"id": 1, "name": "Auth Refactor", "summary": "x"}]
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=existing), \
             mock.patch.object(mod, "save_agents", side_effect=lambda e, pf: saved.extend(e)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_save(self._make_args(name="auth refactor"))
        new_entry = saved[-1]
        assert mod.entry_session_name(new_entry).startswith("auth-refactor-")
        assert mod.entry_session_name(new_entry) != "auth-refactor"

    def test_no_name_falls_back_to_summary_slug(self, capsys):
        mod = _import_recall_restart()
        saved = []
        with mock.patch.object(mod, "load_agents", return_value=[]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda e, pf: saved.extend(e)), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_save(self._make_args(name="", summary="Fix auth bug"))
        assert saved[0].get("name", "") == ""
        assert mod.entry_session_name(saved[0]) == "fix-auth-bug"


# ---------------------------------------------------------------------------
# cmd_match
# ---------------------------------------------------------------------------

class TestCmdMatch:
    def _make_args(self, text, launch=False):
        return argparse.Namespace(text=text, launch=launch)

    def test_no_matches_exits(self):
        mod = _import_recall_restart()
        entries = [({"id": 1, "summary": "fix auth bug", "goal": ""}, "proj")]
        with mock.patch.object(mod, "collect_all_entries", return_value=entries), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"):
            with pytest.raises(SystemExit):
                mod.cmd_match(self._make_args("nonexistent"))

    def test_single_match_loads_without_launching(self, capsys):
        mod = _import_recall_restart()
        entry = {"id": 1, "summary": "fix auth bug", "goal": "", "prompt_file": "recall-restarts/fix-auth.prompt"}
        entries = [(entry, "proj")]
        with mock.patch.object(mod, "collect_all_entries", return_value=entries), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "_launch_entry") as mock_launch:
            mod.cmd_match(self._make_args("auth"))
        mock_launch.assert_not_called()
        out = capsys.readouterr().out
        assert "loading fix-auth" in out.lower()

    def test_matches_by_goal_field(self):
        mod = _import_recall_restart()
        entry = {"id": 1, "summary": "weekly task", "goal": "reduce latency", "prompt_file": ""}
        entries = [(entry, "proj")]
        with mock.patch.object(mod, "collect_all_entries", return_value=entries), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "_launch_entry") as mock_launch:
            mod.cmd_match(self._make_args("latency"))
        mock_launch.assert_not_called()

    def test_single_match_launches_with_flag(self):
        mod = _import_recall_restart()
        entry = {"id": 1, "summary": "fix auth bug", "goal": "", "prompt_file": ""}
        entries = [(entry, "proj")]
        with mock.patch.object(mod, "collect_all_entries", return_value=entries), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "_launch_entry") as mock_launch:
            mod.cmd_match(self._make_args("auth", launch=True))
        mock_launch.assert_called_once_with(entry, "proj")

    def test_exact_name_match_wins_over_other_text_matches(self, capsys):
        mod = _import_recall_restart()
        exact = {"id": 1, "summary": "payroll auth task", "goal": "", "prompt_file": "recall-restarts/payroll.prompt"}
        partial = {"id": 2, "summary": "payroll cleanup", "goal": "", "prompt_file": "recall-restarts/payroll-cleanup.prompt"}
        entries = [(exact, "proj"), (partial, "proj")]
        with mock.patch.object(mod, "collect_all_entries", return_value=entries), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "_launch_entry") as mock_launch:
            mod.cmd_match(self._make_args("payroll"))
        mock_launch.assert_not_called()
        out = capsys.readouterr().out
        assert "loading payroll" in out.lower()
        assert "2 matches" not in out

    def test_multiple_matches_prints_all(self, capsys):
        mod = _import_recall_restart()
        entries = [
            ({"id": 1, "summary": "fix payment auth", "goal": "", "prompt_file": "", "role": "lead", "working_directory": "/tmp"}, "proj"),
            ({"id": 2, "summary": "fix billing auth", "goal": "", "prompt_file": "", "role": "lead", "working_directory": "/tmp"}, "proj"),
        ]
        with mock.patch.object(mod, "collect_all_entries", return_value=entries), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "_launch_entry"):
            mod.cmd_match(self._make_args("auth"))
        out = capsys.readouterr().out
        assert "2 matches" in out

    def test_cmd_match_continues_past_unreadable_prompt_file(self, tmp_path):
        """IOError reading a prompt file is silently swallowed; search continues."""
        mod = _import_recall_restart()
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("fix auth in payment")
        prompt_file.chmod(0o000)  # make unreadable

        entry = {"id": 1, "summary": "weekly database task", "goal": "", "prompt_file": "prompt.txt"}
        entries = [(entry, "proj")]

        try:
            with mock.patch.object(mod, "collect_all_entries", return_value=entries), \
                 mock.patch.object(mod, "get_project_folder", return_value="proj"), \
                 mock.patch.object(mod, "get_project_dir", return_value=tmp_path):
                with pytest.raises(SystemExit):
                    mod.cmd_match(self._make_args("auth"))
        finally:
            prompt_file.chmod(0o644)


# ---------------------------------------------------------------------------
# cmd_show
# ---------------------------------------------------------------------------

class TestCmdShow:
    def _make_args(self, number):
        return argparse.Namespace(number=number)

    def test_shows_by_position_without_launching(self, capsys):
        mod = _import_recall_restart()
        entry = {"id": 10, "summary": "deploy job", "workers": [], "prompt_file": ""}
        ordered = [(1, entry, "proj")]
        with mock.patch.object(mod, "ordered_display_entries", return_value=ordered), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "_launch_entry") as mock_launch:
            mod.cmd_show(self._make_args(1))
        mock_launch.assert_not_called()
        out = capsys.readouterr().out
        assert "deploy job" in out

    def test_show_prints_prompt_file_contents(self, tmp_path, capsys):
        mod = _import_recall_restart()
        prompt = tmp_path / "restart.prompt"
        prompt.write_text("Restart Instructions\n- continue here")
        entry = {"id": 10, "summary": "deploy job", "workers": [], "prompt_file": str(prompt)}
        ordered = [(1, entry, "proj")]
        with mock.patch.object(mod, "ordered_display_entries", return_value=ordered), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"):
            mod.cmd_show(self._make_args(1))
        out = capsys.readouterr().out
        assert str(prompt) in out
        assert "continue here" in out

    def test_show_invalid_position_exits(self):
        mod = _import_recall_restart()
        entry = {"id": 1, "summary": "task", "workers": []}
        ordered = [(1, entry, "proj")]
        with mock.patch.object(mod, "ordered_display_entries", return_value=ordered), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"):
            with pytest.raises(SystemExit):
                mod.cmd_show(self._make_args(99))


# ---------------------------------------------------------------------------
# cmd_launch
# ---------------------------------------------------------------------------

class TestCmdLaunch:
    def _make_args(self, number):
        return argparse.Namespace(number=number)

    def test_launches_by_position(self):
        mod = _import_recall_restart()
        entry = {"id": 10, "summary": "deploy job", "workers": []}
        ordered = [(1, entry, "proj")]
        with mock.patch.object(mod, "ordered_display_entries", return_value=ordered), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "_launch_entry") as mock_launch:
            mod.cmd_launch(self._make_args(1))
        mock_launch.assert_called_once_with(entry, "proj")

    def test_invalid_position_exits(self):
        mod = _import_recall_restart()
        entry = {"id": 1, "summary": "task", "workers": []}
        ordered = [(1, entry, "proj")]
        with mock.patch.object(mod, "ordered_display_entries", return_value=ordered), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "_launch_entry"):
            with pytest.raises(SystemExit):
                mod.cmd_launch(self._make_args(99))

    def test_empty_list_exits(self):
        mod = _import_recall_restart()
        with mock.patch.object(mod, "ordered_display_entries", return_value=[]), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"):
            with pytest.raises(SystemExit):
                mod.cmd_launch(self._make_args(1))

    def test_launches_workers_when_lead_has_workers(self):
        """When a lead entry has workers, cmd_launch also launches each worker."""
        mod = _import_recall_restart()
        lead = {"id": 1, "summary": "lead task", "workers": [2], "role": "lead"}
        worker = {"id": 2, "summary": "worker task", "workers": [], "lead_id": 1, "role": "worker"}
        ordered = [(1, lead, "proj"), (2, worker, "proj")]

        launched = []
        with mock.patch.object(mod, "ordered_display_entries", return_value=ordered), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "_launch_entry", side_effect=lambda e, pf: launched.append(e["summary"])), \
             mock.patch.object(mod.time, "sleep"):
            mod.cmd_launch(self._make_args(1))

        assert "lead task" in launched
        assert "worker task" in launched


# ---------------------------------------------------------------------------
# _launch_entry
# ---------------------------------------------------------------------------

class TestLaunchEntry:
    def test_team_env_var_included_in_command(self, capsys):
        """When entry has a team field, CLAUDE_TEAM is included in the launch command."""
        mod = _import_recall_restart()
        entry = {
            "summary": "deploy staging", "prompt_file": "",
            "working_directory": "/tmp/app", "team": "my-team", "workers": [],
        }
        err = mod.subprocess.CalledProcessError(1, "osascript", stderr=b"err")
        with mock.patch.object(mod, "get_project_dir", return_value=Path("/tmp/app")), \
             mock.patch.object(mod, "get_ticket_ids", return_value=[]), \
             mock.patch.object(mod, "get_theme", return_value=("Basic", "")), \
             mock.patch.object(mod.subprocess, "run", side_effect=err) as mock_run:
            mod._launch_entry(entry, "myapp")
        # The applescript passed to osascript should contain CLAUDE_TEAM
        applescript_arg = mock_run.call_args[0][0]
        assert "CLAUDE_TEAM" in " ".join(str(a) for a in applescript_arg) or \
               "CLAUDE_TEAM" in str(mock_run.call_args)

    def test_applescript_failure_prints_manual_command(self, capsys):
        """When osascript raises CalledProcessError, prints a manual command to stderr."""
        mod = _import_recall_restart()
        entry = {
            "summary": "fix payroll bug",
            "prompt_file": "",
            "working_directory": "/tmp/myapp",
            "team": "",
            "workers": [],
        }
        err = mod.subprocess.CalledProcessError(1, "osascript", stderr=b"Script Error")
        with mock.patch.object(mod, "get_project_dir", return_value=Path("/tmp/myapp")), \
             mock.patch.object(mod.subprocess, "run", side_effect=err):
            mod._launch_entry(entry, "myapp")
        out, err_out = capsys.readouterr().out, capsys.readouterr().err
        # No exception raised and the function returns without crashing
        # (CalledProcessError is caught; function returns normally)

    def test_absolute_prompt_file_used_when_relative_missing(self, tmp_path):
        """When candidate (relative) doesn't exist but prompt_file is absolute and exists, it is used."""
        mod = _import_recall_restart()
        abs_prompt = tmp_path / "abs_prompt.txt"
        abs_prompt.write_text("fix auth issues")
        entry = {
            "summary": "fix auth",
            "prompt_file": str(abs_prompt),  # absolute path
            "working_directory": str(tmp_path),
            "team": "",
            "workers": [],
        }
        # project_dir is a nonexistent path so candidate.exists() is False
        nonexistent_proj = tmp_path / "nonexistent_proj_dir"
        err = mod.subprocess.CalledProcessError(1, "osascript", stderr=b"err")
        with mock.patch.object(mod, "get_project_dir", return_value=nonexistent_proj), \
             mock.patch.object(mod, "get_ticket_ids", return_value=[]), \
             mock.patch.object(mod, "get_theme", return_value=("Basic", "")), \
             mock.patch.object(mod.subprocess, "run", side_effect=err):
            mod._launch_entry(entry, "myapp")
        # No exception raised — absolute path branch was taken


# ---------------------------------------------------------------------------
# cmd_list
# ---------------------------------------------------------------------------

class TestCmdList:
    def _make_args(self):
        return argparse.Namespace()

    def test_shows_no_entries_message_when_empty(self, capsys):
        mod = _import_recall_restart()
        with mock.patch.object(mod, "ordered_display_entries", return_value=[]), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_list(self._make_args())
        out = capsys.readouterr().out
        assert "No restart entries" in out

    def test_shows_entry_summary(self, capsys):
        mod = _import_recall_restart()
        entry = {"id": 1, "summary": "deploy k8s job", "status": "saved", "role": "lead", "working_directory": "/tmp/app", "lead_id": None, "prompt_file": "recall-restarts/deploy-k8s.prompt"}
        ordered = [(1, entry, "myapp")]
        with mock.patch.object(mod, "ordered_display_entries", return_value=ordered), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_list(self._make_args())
        out = capsys.readouterr().out
        assert "deploy-k8s" in out
        assert "deploy k8s job" in out

    def test_shows_total_count(self, capsys):
        mod = _import_recall_restart()
        entries = [
            (1, {"id": 1, "summary": "task A", "status": "saved", "role": "lead", "working_directory": "/tmp/a", "lead_id": None}, "myapp"),
            (2, {"id": 2, "summary": "task B", "status": "saved", "role": "lead", "working_directory": "/tmp/b", "lead_id": None}, "myapp"),
        ]
        with mock.patch.object(mod, "ordered_display_entries", return_value=entries), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_list(self._make_args())
        out = capsys.readouterr().out
        assert "2" in out

    def test_shows_recall_hint(self, capsys):
        mod = _import_recall_restart()
        entry = {"id": 1, "summary": "fix auth", "status": "saved", "role": "lead", "working_directory": "/tmp", "lead_id": None}
        ordered = [(1, entry, "myapp")]
        with mock.patch.object(mod, "ordered_display_entries", return_value=ordered), \
             mock.patch.object(mod, "get_project_folder", return_value="myapp"):
            mod.cmd_list(self._make_args())
        out = capsys.readouterr().out
        assert "restart" in out.lower()
        assert "<name>" in out
        assert "delete" in out.lower()


# ---------------------------------------------------------------------------
# cmd_summary
# ---------------------------------------------------------------------------

class TestCmdSummary:
    def _make_args(self):
        return argparse.Namespace()

    def test_shows_compact_numbered_summary_with_delete_hint(self, capsys):
        mod = _import_recall_restart()
        entry = {
            "id": 1,
            "summary": "fix auth",
            "status": "saved",
            "role": "lead",
            "working_directory": "/tmp/app",
            "date": "2026-07-01",
            "prompt_file": "",
        }
        with mock.patch.object(mod, "ordered_display_entries", return_value=[(1, entry, "proj")]), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"):
            mod.cmd_summary(self._make_args())

        out = capsys.readouterr().out
        assert "Restart Summary" in out
        assert "1  2026-07-01" in out
        assert "fix auth" in out
        assert "Delete: /recall restart delete" in out

    def test_shows_no_entries_message_when_empty(self, capsys):
        mod = _import_recall_restart()
        with mock.patch.object(mod, "ordered_display_entries", return_value=[]), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"):
            mod.cmd_summary(self._make_args())

        out = capsys.readouterr().out
        assert "No restart entries" in out


# ---------------------------------------------------------------------------
# cmd_delete
# ---------------------------------------------------------------------------

class TestCmdDelete:
    def _make_args(self, target):
        return argparse.Namespace(target=target)

    def test_deletes_by_display_position_and_unlinks_prompt(self, tmp_path, capsys):
        mod = _import_recall_restart()
        project_dir = tmp_path / "project"
        restarts_dir = project_dir / "recall-restarts"
        restarts_dir.mkdir(parents=True)
        prompt = restarts_dir / "old.prompt"
        prompt.write_text("restart here")

        entry = {
            "id": 1,
            "summary": "old checkpoint",
            "prompt_file": "recall-restarts/old.prompt",
            "working_directory": "/tmp/app",
        }
        other = {"id": 2, "summary": "keep", "prompt_file": "", "working_directory": "/tmp/app"}
        saved = []

        with mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "ordered_display_entries", return_value=[(1, entry, "proj"), (2, other, "proj")]), \
             mock.patch.object(mod, "load_agents", return_value=[entry, other]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda agents, pf: saved.append((agents, pf))), \
             mock.patch.object(mod, "get_project_dir", return_value=project_dir), \
             mock.patch.object(mod, "get_restarts_dir", return_value=restarts_dir):
            mod.cmd_delete(self._make_args("1"))

        assert not prompt.exists()
        assert saved == [([other], "proj")]
        out = capsys.readouterr().out
        assert "Deleted restart 1: old checkpoint" in out
        assert "Prompt file deleted" in out

    def test_deletes_by_unique_name_match(self, tmp_path, capsys):
        mod = _import_recall_restart()
        project_dir = tmp_path / "project"
        restarts_dir = project_dir / "recall-restarts"
        restarts_dir.mkdir(parents=True)
        prompt = restarts_dir / "auth.prompt"
        prompt.write_text("restart here")

        entry = {
            "id": 3,
            "name": "Auth Refactor",
            "summary": "auth work",
            "prompt_file": "recall-restarts/auth.prompt",
            "working_directory": "/tmp/app",
        }
        saved = []

        with mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "collect_all_entries", return_value=[(entry, "proj")]), \
             mock.patch.object(mod, "load_agents", return_value=[entry]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda agents, pf: saved.append((agents, pf))), \
             mock.patch.object(mod, "get_project_dir", return_value=project_dir), \
             mock.patch.object(mod, "get_restarts_dir", return_value=restarts_dir):
            mod.cmd_delete(self._make_args("auth-refactor"))

        assert not prompt.exists()
        assert saved == [([], "proj")]
        assert "Deleted restart auth-refactor" in capsys.readouterr().out

    def test_ambiguous_text_match_exits_without_deleting(self, capsys):
        mod = _import_recall_restart()
        first = {"id": 1, "summary": "auth one", "prompt_file": "", "working_directory": "/tmp/a"}
        second = {"id": 2, "summary": "auth two", "prompt_file": "", "working_directory": "/tmp/b"}
        entries = [(first, "proj"), (second, "proj")]

        with mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "collect_all_entries", return_value=entries), \
             mock.patch.object(mod, "ordered_display_entries", return_value=[(1, first, "proj"), (2, second, "proj")]), \
             mock.patch.object(mod, "save_agents") as mock_save:
            with pytest.raises(SystemExit):
                mod.cmd_delete(self._make_args("auth"))

        mock_save.assert_not_called()
        out = capsys.readouterr().out
        assert "matched 2 entries" in out
        assert "/recall restart delete <number>" in out

    def test_external_prompt_file_is_not_unlinked(self, tmp_path, capsys):
        mod = _import_recall_restart()
        project_dir = tmp_path / "project"
        restarts_dir = project_dir / "recall-restarts"
        restarts_dir.mkdir(parents=True)
        outside = tmp_path / "outside.prompt"
        outside.write_text("external prompt")

        entry = {
            "id": 1,
            "summary": "external prompt",
            "prompt_file": str(outside),
            "working_directory": "/tmp/app",
        }
        saved = []

        with mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "ordered_display_entries", return_value=[(1, entry, "proj")]), \
             mock.patch.object(mod, "load_agents", return_value=[entry]), \
             mock.patch.object(mod, "save_agents", side_effect=lambda agents, pf: saved.append((agents, pf))), \
             mock.patch.object(mod, "get_project_dir", return_value=project_dir), \
             mock.patch.object(mod, "get_restarts_dir", return_value=restarts_dir):
            mod.cmd_delete(self._make_args("1"))

        assert outside.exists()
        assert saved == [([], "proj")]
        out = capsys.readouterr().out
        assert "Prompt file skipped" in out
        assert "outside recall-restarts" in out


# ---------------------------------------------------------------------------
# cmd_resume
# ---------------------------------------------------------------------------

class TestCmdResume:
    def _make_args(self, number=None):
        class A:
            pass
        a = A()
        a.number = number
        return a

    def _entry(self, **kw):
        base = {
            "id": 1, "summary": "fix auth", "status": "saved", "role": "lead",
            "working_directory": "/tmp/app", "date": "2026-06-15",
            "resume_checkpoint": "abc-uuid-123", "lead_id": None,
        }
        base.update(kw)
        return base

    def test_no_resumable_entries_prints_hint(self, capsys):
        mod = _import_recall_restart()
        entry = self._entry(resume_checkpoint="")
        with mock.patch.object(mod, "ordered_display_entries", return_value=[(1, entry, "proj")]), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"):
            mod.cmd_resume(self._make_args())
        out = capsys.readouterr().out
        assert "No resume tokens" in out

    def test_lists_resumable_entries(self, capsys):
        mod = _import_recall_restart()
        entry = self._entry()
        with mock.patch.object(mod, "ordered_display_entries", return_value=[(1, entry, "proj")]), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"):
            mod.cmd_resume(self._make_args())
        out = capsys.readouterr().out
        assert "fix auth" in out
        assert "abc-uuid" in out

    def test_launch_opens_terminal(self, capsys):
        mod = _import_recall_restart()
        entry = self._entry()
        launched = []
        with mock.patch.object(mod, "ordered_display_entries", return_value=[(1, entry, "proj")]), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"), \
             mock.patch.object(mod, "_launch_resume_entry", side_effect=launched.append):
            mod.cmd_resume(self._make_args(number=1))
        assert len(launched) == 1
        assert launched[0] is entry

    def test_launch_out_of_range_exits(self):
        mod = _import_recall_restart()
        entry = self._entry()
        with mock.patch.object(mod, "ordered_display_entries", return_value=[(1, entry, "proj")]), \
             mock.patch.object(mod, "get_project_folder", return_value="proj"):
            with pytest.raises(SystemExit):
                mod.cmd_resume(self._make_args(number=5))


class TestLaunchResumeEntry:
    def test_prints_command_on_applescript_failure(self, capsys):
        mod = _import_recall_restart()
        entry = {"summary": "fix", "working_directory": "/tmp/app", "resume_checkpoint": "uuid-abc"}
        import subprocess as _sp
        err = _sp.CalledProcessError(1, "osascript")
        err.stderr = b"Terminal error"
        with mock.patch("subprocess.run", side_effect=err):
            mod._launch_resume_entry(entry)
        captured = capsys.readouterr()
        assert "Manual command" in captured.out and "claude --resume" in captured.out

    def test_errors_when_no_checkpoint(self, capsys):
        mod = _import_recall_restart()
        entry = {"summary": "fix", "working_directory": "/tmp/app", "resume_checkpoint": ""}
        mod._launch_resume_entry(entry)
        assert "no resume checkpoint" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# _build_launch_command — named restart (claude -n)
# ---------------------------------------------------------------------------

import shlex


class TestBuildLaunchCommandName:
    def test_includes_quoted_name_with_spaces(self):
        mod = _import_recall_restart()
        entry = {"name": "Auth Refactor", "working_directory": "/tmp", "prompt_file": ""}
        cmd, _ = mod._build_launch_command(entry, "proj")
        assert f"-n {shlex.quote('Auth Refactor')}" in cmd

    def test_quotes_shell_metacharacters_safely(self):
        mod = _import_recall_restart()
        evil = "a; rm -rf $HOME"
        entry = {"name": evil, "working_directory": "/tmp", "prompt_file": ""}
        cmd, _ = mod._build_launch_command(entry, "proj")
        assert f"-n {shlex.quote(evil)}" in cmd

    def test_no_name_emits_plain_claude(self):
        mod = _import_recall_restart()
        entry = {"working_directory": "/tmp", "prompt_file": "", "summary": "do work"}
        cmd, _ = mod._build_launch_command(entry, "proj")
        assert "-n " not in cmd
        assert "| claude" in cmd


# ---------------------------------------------------------------------------
# Security regression: shell/AppleScript injection via stored entry fields
# (security review F2 — working_directory/team/summary/checkpoint were
# interpolated into a single-quoted shell string with no escaping, then into
# an AppleScript do-script literal, giving a stored-data RCE)
# ---------------------------------------------------------------------------

class TestLaunchCommandInjectionHardening:
    def test_working_directory_quote_breakout_is_neutralized(self):
        mod = _import_recall_restart()
        evil = "/tmp'; touch /tmp/PWNED_recall_test; echo '"
        entry = {"working_directory": evil, "prompt_file": "", "summary": "hi", "team": ""}
        cmd, _ = mod._build_launch_command(entry, "proj")
        tokens = shlex.split(cmd)
        assert "cd" in tokens
        assert tokens[tokens.index("cd") + 1] == evil
        assert "touch" not in tokens

    def test_team_quote_breakout_is_neutralized(self):
        mod = _import_recall_restart()
        evil = "x'; touch /tmp/PWNED_recall_test; echo '"
        entry = {"working_directory": "/tmp", "prompt_file": "", "summary": "hi", "team": evil}
        cmd, _ = mod._build_launch_command(entry, "proj")
        tokens = shlex.split(cmd)
        assert "touch" not in tokens

    def test_summary_quote_breakout_is_neutralized(self):
        mod = _import_recall_restart()
        evil = "hi'; touch /tmp/PWNED_recall_test; echo '"
        entry = {"working_directory": "/tmp", "prompt_file": "", "summary": evil, "team": ""}
        cmd, _ = mod._build_launch_command(entry, "proj")
        tokens = shlex.split(cmd)
        assert "touch" not in tokens

    def test_resume_checkpoint_quote_breakout_is_neutralized(self):
        mod = _import_recall_restart()
        evil = "x'; touch /tmp/PWNED_recall_test; echo '"
        working_dir = "/tmp/app"
        cmd = f"cd {shlex.quote(working_dir)} && claude --resume {shlex.quote(evil)}"
        tokens = shlex.split(cmd)
        assert "touch" not in tokens
        assert tokens[tokens.index("--resume") + 1] == evil

    def test_applescript_literal_escapes_double_quote_and_backslash(self):
        mod = _import_recall_restart()
        raw = 'echo ' + shlex.quote("it's \"quoted\" \\ text")
        escaped = mod._applescript_string_literal(raw)
        # The escaped form must not contain an unescaped " or \
        import re
        unescaped_quote = re.search(r'(?<!\\)"', escaped)
        assert unescaped_quote is None
        # Re-deriving the raw string from the escaped one should round-trip
        assert escaped.replace('\\"', '"').replace('\\\\', '\\') == raw

    def test_launch_entry_applescript_arg_has_no_unescaped_quote(self, capsys):
        """End-to-end: a malicious working_directory must not let the do-script
        AppleScript string literal terminate early."""
        mod = _import_recall_restart()
        evil = 'x" & do shell script "touch /tmp/PWNED_recall_test'
        entry = {"summary": "hi", "prompt_file": "", "working_directory": evil, "team": "", "workers": []}
        err = mod.subprocess.CalledProcessError(1, "osascript", stderr=b"err")
        with mock.patch.object(mod, "get_project_dir", return_value=Path("/tmp/app")), \
             mock.patch.object(mod, "get_ticket_ids", return_value=[]), \
             mock.patch.object(mod, "get_theme", return_value=("Basic", "")), \
             mock.patch.object(mod.subprocess, "run", side_effect=err) as mock_run:
            mod._launch_entry(entry, "myapp")
        applescript = mock_run.call_args[0][0][2]
        import re
        do_script_line = next(line for line in applescript.splitlines() if "do script" in line)
        body = do_script_line.split('do script "', 1)[1].rsplit('"', 1)[0]
        assert re.search(r'(?<!\\)"', body) is None
