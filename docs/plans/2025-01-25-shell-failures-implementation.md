# Shell Failures Skill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Claude Code skill that shows SOPs on bash failures and learns new patterns when fixes work.

**Architecture:** PostToolUse hook detects failures/resolutions, reads/writes JSON SOP files. Slash command displays history and manages SOPs. Install script symlinks files and merges hook config.

**Tech Stack:** Python 3 (hooks, bin), JSON (SOPs), Bash (install scripts), Markdown (skill/command definitions)

---

## Task 1: Create Directory Structure

**Files:**
- Create: `shell-failures/` directory with subdirectories

**Step 1: Create the skill directory structure**

```bash
mkdir -p shell-failures/{sops,hooks,commands,bin}
touch shell-failures/SKILL.md
touch shell-failures/install.sh
touch shell-failures/uninstall.sh
touch shell-failures/sops/base.json
touch shell-failures/hooks/post-bash.py
touch shell-failures/commands/failures.md
touch shell-failures/bin/failures
chmod +x shell-failures/install.sh shell-failures/uninstall.sh shell-failures/bin/failures
```

**Step 2: Verify structure**

```bash
find shell-failures -type f | sort
```

Expected:
```
shell-failures/SKILL.md
shell-failures/bin/failures
shell-failures/commands/failures.md
shell-failures/hooks/post-bash.py
shell-failures/install.sh
shell-failures/sops/base.json
shell-failures/uninstall.sh
```

**Step 3: Commit**

```bash
git add shell-failures/
git commit -m "chore: scaffold shell-failures skill directory structure"
```

---

## Task 2: Create Base SOPs JSON

**Files:**
- Create: `shell-failures/sops/base.json`

**Step 1: Write the base SOPs file**

```json
{
  "version": 1,
  "sops": {
    "SHELL_PARSE_ERROR": {
      "description": "zsh cannot parse command substitution or special characters",
      "patterns": ["parse error", "near `('", "parse error near"],
      "causes": [
        "Using $(...) with complex expressions",
        "Nested command substitutions",
        "Special characters not escaped"
      ],
      "fixes": [
        "Use simple pipes instead of $(...)",
        "Split into multiple commands",
        "Use Read tool instead of cat/head"
      ],
      "examples": {
        "bad": "LATEST=$(ls -t *.jsonl | head -1); cat \"$LATEST\"",
        "good": "ls -t *.jsonl | head -1  # then use Read tool"
      }
    },
    "SYNTAX_ERROR": {
      "description": "Python or shell syntax error in inline code",
      "patterns": ["syntaxerror", "syntax error", "invalid syntax"],
      "causes": [
        "f-strings with escaped quotes inside dict access",
        "Mixing single/double quotes incorrectly",
        "Heredoc escaping issues"
      ],
      "fixes": [
        "Extract dict values to variables before f-string",
        "Write Python to a script file instead of -c",
        "Use single quotes for outer string in python3 -c"
      ],
      "examples": {
        "bad": "python3 -c 'print(f\"{d[\\\"key\\\"]}\")'",
        "good": "python3 -c 'val = d[\"key\"]; print(f\"{val}\")'"
      }
    },
    "COMMAND_NOT_FOUND": {
      "description": "Command or binary doesn't exist or isn't in PATH",
      "patterns": ["command not found", "not found"],
      "causes": [
        "Tool not installed",
        "Wrong command name",
        "PATH not set correctly"
      ],
      "fixes": [
        "Check if installed: which <command>",
        "Install if needed: brew install <package>",
        "Use alternative (grep instead of rg)"
      ],
      "examples": {
        "bad": "rg pattern  # if ripgrep not installed",
        "good": "grep -r pattern  # or: brew install ripgrep"
      }
    },
    "PERMISSION_DENIED": {
      "description": "No permission to execute or access file",
      "patterns": ["permission denied"],
      "causes": [
        "Script not executable",
        "File owned by different user",
        "Directory permissions too restrictive"
      ],
      "fixes": [
        "Make script executable: chmod +x script.sh",
        "Run with interpreter: python3 script.py",
        "Check file ownership: ls -la file"
      ],
      "examples": {
        "bad": "./script.py  # not executable",
        "good": "python3 ./script.py"
      }
    },
    "FILE_NOT_FOUND": {
      "description": "File or directory doesn't exist",
      "patterns": ["no such file", "not found", "does not exist"],
      "causes": [
        "Typo in path",
        "File not created yet",
        "Wrong working directory"
      ],
      "fixes": [
        "Verify path exists: ls -la <parent_dir>",
        "Check current directory: pwd",
        "Create directory if needed: mkdir -p <dir>",
        "Use absolute paths"
      ],
      "examples": {
        "bad": "cat config.json  # in wrong directory",
        "good": "ls -la . && cat ./config.json"
      }
    },
    "NON_ZERO_EXIT": {
      "description": "Command ran but returned non-zero exit code",
      "patterns": ["exit code", "exited with", "returned"],
      "causes": [
        "Command logic failed",
        "Missing required arguments",
        "Invalid input data"
      ],
      "fixes": [
        "Check stderr for details",
        "For grep: exit 1 means no match (often ok)",
        "Add || true if exit code doesn't matter"
      ],
      "examples": {
        "bad": "grep pattern file.txt  # exits 1 if no match",
        "good": "grep pattern file.txt || echo 'No matches'"
      }
    }
  }
}
```

**Step 2: Validate JSON**

```bash
python3 -c "import json; json.load(open('shell-failures/sops/base.json')); print('Valid JSON')"
```

Expected: `Valid JSON`

**Step 3: Commit**

```bash
git add shell-failures/sops/base.json
git commit -m "feat: add base SOPs for common shell errors"
```

---

## Task 3: Create SOP Library Module

**Files:**
- Create: `shell-failures/lib/sops.py`

**Step 1: Create lib directory**

```bash
mkdir -p shell-failures/lib
touch shell-failures/lib/__init__.py
```

**Step 2: Write the SOP library**

```python
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


def save_sop(name: str, sop: dict, scope: str = "global") -> bool:
    """Save a new SOP to global or project file."""
    if scope == "global":
        path = GLOBAL_SOPS_PATH
    else:
        path = Path.cwd() / PROJECT_SOPS_NAME

    # Ensure directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing
    data = {"version": 1, "sops": {}}
    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Add/update SOP
    if "sops" not in data:
        data["sops"] = {}
    data["sops"][name] = sop

    # Save
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except IOError:
        return False
```

**Step 3: Verify module loads**

```bash
cd shell-failures && python3 -c "from lib.sops import load_sops, match_error; print('Module loads')" && cd ..
```

Expected: `Module loads`

**Step 4: Commit**

```bash
git add shell-failures/lib/
git commit -m "feat: add SOP library for loading and matching"
```

---

## Task 4: Create PostToolUse Hook

**Files:**
- Create: `shell-failures/hooks/post-bash.py`

**Step 1: Write the hook**

```python
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
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
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

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})
    tool_response = hook_input.get("tool_response", {})

    # Only process Bash
    if tool_name != "Bash":
        sys.exit(0)

    command = tool_input.get("command", "")
    exit_code = tool_response.get("exitCode", 0)
    stderr = tool_response.get("stderr", "")
    stdout = tool_response.get("stdout", "")

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
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  BASH FAILED: {name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{sop_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ESCALATION: 1st fail → try SOP | 2nd → alternatives | 3rd → ASK USER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        else:
            write_state("UNKNOWN", command, error_msg)
            feedback = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  BASH FAILED: UNKNOWN ERROR TYPE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

No matching SOP found. Try:
  1. Read the error message carefully
  2. Try a simpler version of the command
  3. ASK THE USER for help

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        output = {
            "decision": "allow",
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
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ That command worked after {state['error_type']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Failed: {truncate(state['failed_command'])}
Worked: {truncate(command)}

Save as SOP? Reply: "save global", "save project", or continue working
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

            output = {
                "decision": "allow",
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": feedback
                }
            }
            print(json.dumps(output))
        else:
            # No state, just allow
            print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
```

**Step 2: Make executable**

```bash
chmod +x shell-failures/hooks/post-bash.py
```

**Step 3: Verify hook runs**

```bash
echo '{"tool_name": "Bash", "tool_input": {"command": "test"}, "tool_response": {"exitCode": 0}}' | python3 shell-failures/hooks/post-bash.py
```

Expected: `{"decision": "allow"}`

**Step 4: Commit**

```bash
git add shell-failures/hooks/post-bash.py
git commit -m "feat: add PostToolUse hook for failure detection"
```

---

## Task 5: Create /failures Command

**Files:**
- Create: `shell-failures/commands/failures.md`
- Create: `shell-failures/bin/failures`

**Step 1: Write the command definition**

```markdown
---
name: failures
description: Show shell command failures from this session with resolutions and SOPs
---

Analyze bash command failures and show what worked.

Usage:
- `/failures` - Show recent failures with resolutions
- `/failures --sop` - Include SOP guidance for each error type
- `/failures --all` - Show all SOPs (global + project)
- `/failures --recent N` - Show last N failure groups (default: 10)

Run: `python3 ~/.claude/bin/failures "$PWD" $ARGUMENTS`

After showing output, if there are unresolved failures, suggest fixes based on SOPs.
```

**Step 2: Write the command implementation**

```python
#!/usr/bin/env python3
"""
/failures command - Show shell failures with resolutions and SOPs.
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime

# Add lib to path
SKILL_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SKILL_DIR / "lib"))
from sops import load_sops, match_error, format_sop


def get_session_dir(project_path: str) -> Path:
    """Convert project path to Claude's session directory."""
    project_dir = project_path.replace("/", "-")
    return Path.home() / ".claude" / "projects" / project_dir


def get_latest_session(session_dir: Path) -> Path | None:
    """Get most recent session file."""
    jsonl_files = list(session_dir.glob("*.jsonl"))
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda f: f.stat().st_mtime)


def extract_commands(session_file: Path) -> list[dict]:
    """Extract bash commands with success/failure status."""
    commands = {}
    results = {}

    with open(session_file) as f:
        for idx, line in enumerate(f):
            try:
                entry = json.loads(line.strip())

                if entry.get("type") == "assistant":
                    content = entry.get("message", {}).get("content", [])
                    for item in content:
                        if item.get("type") == "tool_use" and item.get("name") == "Bash":
                            tool_id = item.get("id")
                            cmd = item.get("input", {}).get("command", "")
                            commands[tool_id] = {"command": cmd, "index": idx}

                if entry.get("type") == "user":
                    content = entry.get("message", {}).get("content", [])
                    for item in content:
                        if isinstance(item, dict) and "tool_use_id" in item:
                            tool_id = item.get("tool_use_id")
                            is_error = item.get("is_error", False)
                            error_content = item.get("content", "") if is_error else ""
                            results[tool_id] = {
                                "is_error": is_error,
                                "error_msg": error_content
                            }
            except json.JSONDecodeError:
                continue

    sequence = []
    for tool_id, cmd_info in commands.items():
        if tool_id in results:
            sequence.append({
                "command": cmd_info["command"],
                "is_error": results[tool_id]["is_error"],
                "error_msg": results[tool_id]["error_msg"],
                "index": cmd_info["index"]
            })

    sequence.sort(key=lambda x: x["index"])
    return sequence


def group_failures(commands: list[dict]) -> list[dict]:
    """Group consecutive failures followed by success."""
    groups = []
    current_failures = []

    for cmd in commands:
        if cmd["is_error"]:
            current_failures.append(cmd)
        else:
            if current_failures:
                groups.append({
                    "failures": current_failures.copy(),
                    "resolution": cmd["command"]
                })
                current_failures = []

    if current_failures:
        groups.append({
            "failures": current_failures.copy(),
            "resolution": None
        })

    return groups


def truncate(s: str, length: int = 100) -> str:
    if len(s) > length:
        return s[:length] + "..."
    return s


def show_all_sops(sops: dict):
    """Show all SOPs."""
    print("=== All SOPs ===\n")
    for name, sop in sops.get("sops", {}).items():
        print(format_sop(name, sop))
        print()


def main():
    args = sys.argv[1:]
    project_path = args[0] if args else os.getcwd()

    show_sop = "--sop" in args
    show_all = "--all" in args
    recent_n = 10

    if "--recent" in args:
        idx = args.index("--recent")
        if idx + 1 < len(args):
            try:
                recent_n = int(args[idx + 1])
            except ValueError:
                pass

    sops = load_sops()

    if show_all:
        show_all_sops(sops)
        return

    session_dir = get_session_dir(project_path)

    if not session_dir.exists():
        print(f"No session history found for: {project_path}")
        sys.exit(1)

    session_file = get_latest_session(session_dir)

    if not session_file:
        print("No session files found")
        sys.exit(1)

    print(f"=== Shell Failures & Resolutions ===")
    print(f"=== Session: {session_file.stem} ===\n")

    commands = extract_commands(session_file)
    failure_groups = group_failures(commands)

    if not failure_groups:
        print("No command failures found in this session.")
        return

    failure_groups = failure_groups[-recent_n:]
    patterns = {}

    for i, group in enumerate(failure_groups, 1):
        failures = group["failures"]
        resolution = group["resolution"]

        # Determine error type
        first_error = failures[0]["error_msg"]
        match = match_error(first_error, sops)
        error_type = match[0] if match else "UNKNOWN"

        print(f"━━━ FAILURE #{i}: {error_type} ━━━")

        for fail in failures:
            print(f"  ✗ {truncate(fail['command'], 80)}")
            print(f"    → {truncate(fail['error_msg'], 60)}")

        if resolution:
            print(f"  ✓ {truncate(resolution, 80)}")

            if error_type not in patterns:
                patterns[error_type] = 0
            patterns[error_type] += 1
        else:
            print("  (unresolved)")

        if show_sop and match:
            print()
            print(format_sop(match[0], match[1]))

        print()

    # Summary
    if patterns:
        print("━━━ PATTERNS LEARNED ━━━")
        for error_type, count in sorted(patterns.items(), key=lambda x: -x[1]):
            print(f"  {error_type} ({count}x)")
        print()

    resolved = sum(1 for g in failure_groups if g["resolution"])
    print(f"Total: {len(failure_groups)} failures, {resolved} resolved")


if __name__ == "__main__":
    main()
```

**Step 3: Make executable**

```bash
chmod +x shell-failures/bin/failures
```

**Step 4: Verify command runs**

```bash
python3 shell-failures/bin/failures --all
```

Expected: Shows all SOPs from base.json

**Step 5: Commit**

```bash
git add shell-failures/commands/failures.md shell-failures/bin/failures
git commit -m "feat: add /failures command"
```

---

## Task 6: Create Install Script

**Files:**
- Create: `shell-failures/install.sh`
- Create: `shell-failures/lib/install-hooks.py`

**Step 1: Write the hook installer helper**

```python
#!/usr/bin/env python3
"""
Merge shell-failures hook into existing hooks.json
"""

import json
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
HOOKS_FILE = CLAUDE_DIR / "hooks.json"
SKILL_DIR = Path(__file__).parent.parent

HOOK_CONFIG = {
    "matcher": "Bash",
    "hooks": [
        {
            "type": "command",
            "command": f"python3 {SKILL_DIR / 'hooks' / 'post-bash.py'}",
            "timeout": 10
        }
    ]
}


def main():
    # Load existing hooks
    config = {"hooks": {}}
    if HOOKS_FILE.exists():
        try:
            with open(HOOKS_FILE) as f:
                config = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    if "hooks" not in config:
        config["hooks"] = {}

    # Add/update PostToolUse
    if "PostToolUse" not in config["hooks"]:
        config["hooks"]["PostToolUse"] = []

    # Check if already installed
    post_hooks = config["hooks"]["PostToolUse"]
    already_installed = any(
        "shell-failures" in str(h.get("hooks", [{}])[0].get("command", ""))
        for h in post_hooks
    )

    if not already_installed:
        config["hooks"]["PostToolUse"].append(HOOK_CONFIG)

    # Save
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    with open(HOOKS_FILE, "w") as f:
        json.dump(config, f, indent=2)

    print("✓ Hook config updated")


if __name__ == "__main__":
    main()
```

**Step 2: Write the install script**

```bash
#!/bin/bash
set -e

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"

echo "Installing shell-failures skill..."

# Create directories
mkdir -p "$CLAUDE_DIR/bin"
mkdir -p "$CLAUDE_DIR/commands"
mkdir -p "$CLAUDE_DIR/shell-failures"

# Symlink command definition
ln -sf "$SKILL_DIR/commands/failures.md" "$CLAUDE_DIR/commands/failures.md"
echo "✓ Linked /failures command"

# Symlink binary
ln -sf "$SKILL_DIR/bin/failures" "$CLAUDE_DIR/bin/failures"
echo "✓ Linked failures binary"

# Copy base SOPs (don't overwrite existing)
if [ ! -f "$CLAUDE_DIR/shell-failures/sops.json" ]; then
    cp "$SKILL_DIR/sops/base.json" "$CLAUDE_DIR/shell-failures/sops.json"
    echo "✓ Copied base SOPs"
else
    echo "✓ SOPs already exist (preserved)"
fi

# Install hooks
python3 "$SKILL_DIR/lib/install-hooks.py"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ shell-failures installed!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Commands:"
echo "  /failures          - Show failures with resolutions"
echo "  /failures --sop    - Include SOP guidance"
echo "  /failures --all    - Show all SOPs"
echo ""
echo "SOPs stored at:"
echo "  Global:  ~/.claude/shell-failures/sops.json"
echo "  Project: .claude/sops.json (optional)"
echo ""
```

**Step 3: Verify install script is executable**

```bash
chmod +x shell-failures/install.sh shell-failures/lib/install-hooks.py
```

**Step 4: Commit**

```bash
git add shell-failures/install.sh shell-failures/lib/install-hooks.py
git commit -m "feat: add install script with hook merger"
```

---

## Task 7: Create Uninstall Script

**Files:**
- Create: `shell-failures/uninstall.sh`

**Step 1: Write the uninstall script**

```bash
#!/bin/bash
set -e

CLAUDE_DIR="$HOME/.claude"

echo "Uninstalling shell-failures skill..."

# Remove symlinks
rm -f "$CLAUDE_DIR/commands/failures.md"
rm -f "$CLAUDE_DIR/bin/failures"
echo "✓ Removed symlinks"

# Note: We don't remove sops.json to preserve user customizations
echo "✓ SOPs preserved at ~/.claude/shell-failures/sops.json"

# Note: Hook removal would require parsing hooks.json
echo "⚠ Hook entry in ~/.claude/hooks.json must be removed manually"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ shell-failures uninstalled"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
```

**Step 2: Make executable**

```bash
chmod +x shell-failures/uninstall.sh
```

**Step 3: Commit**

```bash
git add shell-failures/uninstall.sh
git commit -m "feat: add uninstall script"
```

---

## Task 8: Create SKILL.md

**Files:**
- Create: `shell-failures/SKILL.md`

**Step 1: Write the skill definition**

```markdown
---
name: shell-failures
description: Use when bash commands fail - shows SOPs for common errors and proposes new patterns when fixes work
---

# Shell Failures

Shows Standard Operating Procedures when bash commands fail. Learns new patterns when fixes work.

## How It Works

1. **On failure:** Hook matches error against SOPs, shows relevant fix steps
2. **On success after failure:** Proposes saving the pattern as new SOP
3. **On `/failures`:** Shows failure history with resolutions

## Commands

- `/failures` - Show recent failures with what worked
- `/failures --sop` - Include full SOP for each error type
- `/failures --all` - List all SOPs (global + project)

## SOPs

Stored as JSON:
- Global: `~/.claude/shell-failures/sops.json`
- Project: `.claude/sops.json` (overrides global)

## Saving New SOPs

When a fix works, you'll see:
```
✅ That command worked after SHELL_PARSE_ERROR
Save as SOP? Reply: "save global", "save project", or continue
```

Reply with your choice to save the pattern.
```

**Step 2: Commit**

```bash
git add shell-failures/SKILL.md
git commit -m "feat: add SKILL.md definition"
```

---

## Task 9: Test Full Installation

**Step 1: Run install**

```bash
./shell-failures/install.sh
```

Expected output includes "✅ shell-failures installed!"

**Step 2: Verify symlinks**

```bash
ls -la ~/.claude/commands/failures.md
ls -la ~/.claude/bin/failures
```

Expected: Both point to shell-failures directory

**Step 3: Verify SOPs copied**

```bash
cat ~/.claude/shell-failures/sops.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d[\"sops\"])} SOPs loaded')"
```

Expected: `6 SOPs loaded`

**Step 4: Verify hook added**

```bash
cat ~/.claude/hooks.json | grep -q "post-bash.py" && echo "Hook installed" || echo "Hook missing"
```

Expected: `Hook installed`

**Step 5: Test /failures command**

```bash
python3 ~/.claude/bin/failures --all
```

Expected: Shows all 6 SOPs

**Step 6: Commit any fixes if needed**

---

## Task 10: Final Cleanup and Documentation

**Step 1: Update README**

Create `shell-failures/README.md`:

```markdown
# shell-failures

A Claude Code skill that helps Claude learn from shell command failures.

## Install

```bash
git clone https://github.com/you/shell-failures ~/.claude/skills/shell-failures
~/.claude/skills/shell-failures/install.sh
```

## Usage

The skill works automatically:
- When a bash command fails, you'll see the relevant SOP
- When a fix works, you'll be asked to save the pattern

Commands:
- `/failures` - Show failures with resolutions
- `/failures --sop` - Include SOP details
- `/failures --all` - List all SOPs

## Customization

Edit `~/.claude/shell-failures/sops.json` to customize global SOPs.

Create `.claude/sops.json` in a project for project-specific SOPs.

## Uninstall

```bash
~/.claude/skills/shell-failures/uninstall.sh
```
```

**Step 2: Commit**

```bash
git add shell-failures/README.md
git commit -m "docs: add README for shell-failures skill"
```

**Step 3: Final commit with all files**

```bash
git status
```

Verify clean working tree. If any unstaged files, add and commit.
