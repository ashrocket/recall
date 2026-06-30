# recall-skill Consolidation - 2025-01-26

## Summary

Consolidated the `shell-failures/` subdirectory into the main repo structure, updated install script with selective installation options, and updated README to document all three skills.

## Changes Made

### 1. Install Script Updates (`install.sh`)

Added command-line options for selective installation:
- `--all` (default) - Install all 3 skills
- `--recall` - Session memory only
- `--failures` - Bash failure SOPs only
- `--history` - Command history only (no hooks)
- `--minimal` - Alias for `--history`

Options can be combined: `--recall --history`

### 2. Consolidated shell-failures/ into main repo

**Removed:** `shell-failures/` subdirectory (was a separate standalone package)

**Added:**
- `lib/sops.py` - Shared SOP library (loading, matching, formatting)
- `lib/__init__.py` - Package marker
- `sops/base.json` - Default SOPs (10 error types)

**Updated:**
- `bin/claude-failures` - Now uses shared lib, supports `--all` flag
- `hooks/on-bash-failure.py` - Advanced version with state tracking and SOP learning
- `commands/failures.md` - Added `--all` option documentation

### 3. README Updates

- Documents all 3 skills with overhead levels
- Installation options with examples
- "Choosing What to Install" guidance section
- Complete file structure showing all components
- SOP customization locations

## New Features

### Failures Skill Improvements

1. **External SOP files** - SOPs are now JSON data, not hardcoded in Python
2. **Layered SOPs** - Global + per-project (`.claude/sops.json` overrides global)
3. **State tracking** - Remembers last failure to detect when a fix works
4. **SOP learning** - Prompts to save new patterns when fixes work
5. **`--all` flag** - Show all available SOPs

### Install Script Improvements

1. **Selective installation** - Choose which skills to install
2. **Overhead awareness** - Help text shows hook overhead per skill
3. **Non-destructive SOP install** - Won't overwrite existing SOPs
4. **Dynamic hook config** - Shows only the hooks you need

## File Structure (Final)

```
recall-skill/
├── bin/
│   ├── claude-failures       # /failures command
│   ├── claude-history        # /history command
│   ├── index-session.py      # SessionEnd hook
│   ├── recall-sessions.py    # /recall command
│   └── session-context.py    # SessionStart hook
├── commands/
│   ├── failures.md           # /failures skill definition
│   ├── history.md            # /history skill definition
│   └── recall.md             # /recall skill definition
├── hooks/
│   └── on-bash-failure.py    # PostToolUse Bash hook
├── lib/
│   ├── __init__.py
│   └── sops.py               # Shared SOP library
├── sops/
│   └── base.json             # Default SOPs
├── docs/plans/
│   └── *.md                  # Planning documents
├── install.sh                # Installer with options
├── README.md                 # Documentation
└── hooks-config.json         # Example hook config
```

## Installation Locations

When installed, files go to:

```
~/.claude/
├── bin/                      # All scripts
├── commands/                 # Skill definitions
├── hooks/                    # Hook scripts
├── lib/                      # Shared library
└── shell-failures/
    └── sops.json             # Global SOPs (from sops/base.json)
```

## Next Steps

- [ ] Test all 3 skills work correctly after consolidation
- [ ] Consider adding SKILL.md for auto-trigger capability
- [ ] Add more SOPs based on common errors
- [ ] Consider semantic search for recall skill
