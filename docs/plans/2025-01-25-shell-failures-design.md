# Shell Failures Skill Design

**Date:** 2025-01-25
**Status:** Approved

## Overview

A Claude Code skill that helps Claude learn from shell command failures. When a bash command fails, the skill shows relevant SOPs (Standard Operating Procedures). When a fix works, it proposes saving the pattern for future use.

## Key Decisions

| Aspect | Decision |
|--------|----------|
| SOP Storage | JSON file, layered (global + per-project) |
| Learning | Propose on resolution, user approves |
| Distribution | Git clone + install script |
| Commands | Single `/failures` with flags |
| Hook | PostToolUse on Bash, tracks state for resolution detection |

## Directory Structure

### Skill Repository

```
shell-failures/
├── SKILL.md                 # Skill definition for Claude
├── install.sh               # Installation script
├── uninstall.sh             # Clean removal
├── sops/
│   └── base.json            # Ships with skill (core SOPs)
├── hooks/
│   └── post-bash.py         # PostToolUse hook
├── commands/
│   └── failures.md          # Slash command definition
└── bin/
    └── failures             # Command implementation
```

### After Installation

```
~/.claude/
├── hooks.json               # Updated to include our hook
├── commands/
│   └── failures.md          # Symlinked
├── bin/
│   └── failures             # Symlinked
└── shell-failures/
    └── sops.json            # Global SOPs (copied from base.json, editable)
```

### Per-Project Overrides

```
your-project/
└── .claude/
    └── sops.json            # Project-specific SOPs (optional)
```

## SOP JSON Schema

```json
{
  "version": 1,
  "sops": {
    "SHELL_PARSE_ERROR": {
      "description": "zsh cannot parse command substitution or special characters",
      "patterns": ["parse error", "near `('"],
      "causes": [
        "Using $(...) with complex expressions",
        "Nested command substitutions"
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
    "BITBUCKET_CLI_AUTH": {
      "description": "Bitbucket CLI authentication failed",
      "patterns": ["unauthorized", "401", "bitbucket"],
      "causes": ["Token expired", "Wrong token file"],
      "fixes": [
        "Check token at ~/.bb-cli-personal-token",
        "Regenerate token in Bitbucket settings"
      ],
      "examples": {
        "bad": "bb pr list  # with expired token",
        "good": "cat ~/.bb-cli-personal-token && bb pr list"
      }
    }
  }
}
```

**Key points:**
- `patterns` - regex/substring matches to categorize errors
- Layering: project `sops.json` merges with global (project wins on conflict)
- `version` field for future schema migrations

## Hook Behavior

The `post-bash.py` hook handles two jobs:

### Job 1: On Failure → Show SOP

```
Bash command fails
    ↓
Hook reads error message
    ↓
Match against patterns in sops.json (project first, then global)
    ↓
Inject SOP guidance into context
    ↓
Write failure to state file: ~/.claude/shell-failures/.last-failure
```

### Job 2: On Success After Failure → Propose SOP

```
Bash command succeeds
    ↓
Check if .last-failure exists and is recent (< 5 min)
    ↓
If yes: "This fixed the error. Save as SOP? [global/project/skip]"
    ↓
Clear .last-failure
```

### State File (`.last-failure`)

```json
{
  "timestamp": "2025-01-25T10:30:00Z",
  "error_type": "SHELL_PARSE_ERROR",
  "failed_command": "LATEST=$(ls -t *.jsonl | head -1)",
  "error_message": "parse error near `('"
}
```

### Proposal Prompt

Injected via hook when resolution detected:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ That command worked after SHELL_PARSE_ERROR

Failed: LATEST=$(ls -t *.jsonl | head -1)
Worked: ls -t *.jsonl | head -1

Save as SOP? Reply: "save global", "save project", or continue working
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## The `/failures` Command

### Usage

```
/failures              # Show recent failure→resolution groups
/failures --sop        # Include SOP guidance for each error type
/failures --all        # Show all SOPs (global + project)
/failures --edit       # Open sops.json in editor
/failures --recent N   # Show last N failure groups (default: 10)
```

### Default Output

```
=== Shell Failures & Resolutions ===
=== Session: 2025-01-25-abc123 ===

━━━ FAILURE #1: SHELL_PARSE_ERROR ━━━
  ✗ LATEST=$(ls -t *.jsonl | head -1)
    → parse error near `('
  ✓ ls -t *.jsonl | head -1

━━━ FAILURE #2: PERMISSION_DENIED ━━━
  ✗ ./script.py
    → permission denied
  ✗ chmod +x ./script.py && ./script.py
    → No such file
  ✓ python3 script.py

━━━ PATTERNS LEARNED ━━━
SHELL_PARSE_ERROR (2x): Avoid $(...), use pipes
PERMISSION_DENIED (1x): Use python3 explicitly

Total: 3 failures, 2 resolved
```

## Installation

### install.sh

```bash
#!/bin/bash
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"

# Create directories
mkdir -p "$CLAUDE_DIR/bin"
mkdir -p "$CLAUDE_DIR/commands"
mkdir -p "$CLAUDE_DIR/shell-failures"

# Symlink command and binary
ln -sf "$SKILL_DIR/commands/failures.md" "$CLAUDE_DIR/commands/"
ln -sf "$SKILL_DIR/bin/failures" "$CLAUDE_DIR/bin/"

# Copy base SOPs (don't overwrite if exists)
if [ ! -f "$CLAUDE_DIR/shell-failures/sops.json" ]; then
  cp "$SKILL_DIR/sops/base.json" "$CLAUDE_DIR/shell-failures/sops.json"
fi

# Add hook to hooks.json (merge with existing)
python3 "$SKILL_DIR/install-hooks.py"

echo "✓ shell-failures installed"
echo "  Commands: /failures"
echo "  SOPs: ~/.claude/shell-failures/sops.json"
```

### What It Does

1. Symlinks command/binary (updates when you `git pull`)
2. Copies base SOPs once (your edits preserved)
3. Merges hook config into existing `~/.claude/hooks.json`

### uninstall.sh

Reverses all of the above cleanly.

## Flow Diagram

```
Failure → Hook shows SOP → Fix attempted → Success →
  "Save as SOP? [global/project/skip]" → User approves → sops.json updated
```

## Future Considerations

- Export/import SOPs for sharing
- SOP statistics (which ones fire most often)
- Integration with `/recall` for cross-session pattern analysis
