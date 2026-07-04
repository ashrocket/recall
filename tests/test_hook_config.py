import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _hook_command(event_name):
    config = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    group = config["hooks"][event_name][0]
    return group["hooks"][0]["command"]


def test_install_hook_commands_use_wrappers():
    assert _hook_command("SessionStart") == "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session-start"
    assert _hook_command("SessionEnd") == "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session-end"
    assert _hook_command("PostToolUse") == "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/bash-failure"

    for event_name in ("SessionStart", "SessionEnd", "PostToolUse"):
        command = _hook_command(event_name)
        assert "python3 " not in command
        assert not command.endswith(".py")


def test_hook_wrapper_scripts_are_executable():
    for name in ("session-start", "session-end", "bash-failure"):
        path = ROOT / "hooks" / "scripts" / name
        assert path.exists()
        assert os.access(path, os.X_OK)
