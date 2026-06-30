#!/usr/bin/env python3
"""
PostToolUse hook for Bash commands.
Job 1: On failure - show matching SOP, save state
Job 2: On success after failure - propose new SOP
"""

import json
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Add lib to path
LIB_DIR = Path(__file__).resolve().parent.parent.parent / "lib"
INSTALLED_LIB_DIR = Path.home() / ".claude" / "lib"

# Try installed location first, then source location
if INSTALLED_LIB_DIR.exists():
    sys.path.insert(0, str(INSTALLED_LIB_DIR))
elif LIB_DIR.exists():
    sys.path.insert(0, str(LIB_DIR))

from sops import load_sops, match_error, format_sop

STATE_FILE = Path.home() / ".claude" / "shell-failures" / ".last-failure"
RESOLUTION_WINDOW = timedelta(minutes=5)


def read_state() -> dict | None:
    """Read last failure state if recent enough."""
    if not STATE_FILE.exists():
        return None

    try:
        with open(STATE_FILE) as f:
            state = json.load(f)

        timestamp = datetime.fromisoformat(state["timestamp"])
        if datetime.now() - timestamp > RESOLUTION_WINDOW:
            STATE_FILE.unlink(missing_ok=True)
            return None

        return state
    except (json.JSONDecodeError, IOError, KeyError):
        return None


def write_state(error_type: str, failed_cmd: str, error_msg: str):
    """Save failure state for resolution detection."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    state = {
        "timestamp": datetime.now().isoformat(),
        "error_type": error_type,
        "failed_command": failed_cmd[:500],
        "error_message": error_msg[:500]
    }

    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def clear_state():
    """Clear failure state after resolution."""
    STATE_FILE.unlink(missing_ok=True)


def truncate(s: str, length: int = 100) -> str:
    """Truncate string for display."""
    if len(s) > length:
        return s[:length] + "..."
    return s


def main():
    # Read hook input
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, IOError):
        sys.exit(0)

    try:
        tool_name = hook_input.get("tool_name", "")
        tool_input = hook_input.get("tool_input", {})
        tool_response = hook_input.get("tool_response", {})

        # Only process Bash
        if tool_name != "Bash":
            sys.exit(0)

        command = tool_input.get("command", "") or ""
        exit_code = tool_response.get("exitCode", 0) or 0
        stderr = tool_response.get("stderr", "") or ""  # Handle None
        stdout = tool_response.get("stdout", "") or ""  # Handle None

        sops = load_sops()

        # Check if this is a failure
        is_error = exit_code != 0 and stderr

        if is_error:
            # Job 1: Show SOP on failure
            error_msg = stderr if stderr else stdout
            match = match_error(error_msg, sops)

            if match:
                name, sop = match
                sop_text = format_sop(name, sop)
                write_state(name, command, error_msg)

                feedback = f"""
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
\u26a0\ufe0f  BASH FAILED: {name}
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501

{sop_text}

\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
ESCALATION: 1st fail \u2192 try SOP | 2nd \u2192 alternatives | 3rd \u2192 ASK USER
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
"""
            else:
                write_state("UNKNOWN", command, error_msg)
                feedback = f"""
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
\u26a0\ufe0f  BASH FAILED: UNKNOWN ERROR TYPE
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501

No matching SOP found. Try:
  1. Read the error message carefully
  2. Try a simpler version of the command
  3. ASK THE USER for help

\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
"""

            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": feedback
                }
            }
            print(json.dumps(output))

        else:
            # Job 2: Check if this resolves a previous failure
            state = read_state()

            if state:
                clear_state()

                feedback = f"""
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
\u2705 That command worked after {state['error_type']}
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501

Failed: {truncate(state['failed_command'])}
Worked: {truncate(command)}

Save as SOP? Reply: "save global", "save project", or continue working
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
"""

                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": feedback
                    }
                }
                print(json.dumps(output))
            else:
                # No state, nothing to do
                sys.exit(0)

    except Exception:
        # Fail silently - don't crash the hook
        sys.exit(0)


if __name__ == "__main__":
    main()
