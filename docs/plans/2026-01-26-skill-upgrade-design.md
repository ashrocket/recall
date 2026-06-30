# Skill Upgrade System Design

**Date:** 2026-01-26
**Status:** Approved

## Overview

A system for versioning, installing, upgrading, and migrating Claude Code skills with dependency tracking.

## SKILL.md Format

Each skill has a `SKILL.md` with YAML frontmatter:

```yaml
---
name: recall
version: 1.3.0
description: Session recall and failure tracking

installs:
  bin:
    - session-context.py
    - index-session.py
    - recall-sessions.py
  hooks:
    - on-bash-failure.py
  lib:
    - sops.py
  commands:
    - recall.md
    - failures.md
    - history.md

hooks:
  SessionStart:
    command: python3 ~/.claude/bin/session-context.py
    timeout: 5
  SessionEnd:
    command: python3 ~/.claude/bin/index-session.py
    timeout: 30
  PostToolUse:
    matcher: Bash
    command: python3 ~/.claude/hooks/on-bash-failure.py
    timeout: 10

dependencies:
  - core-utils>=1.0.0
---

# Recall Skill

Session memory and failure tracking...
```

## Installed State Tracking

Installed skills tracked in `~/.claude/skills.json`:

```json
{
  "installed": {
    "recall": {
      "version": "1.3.0",
      "source": "/Users/exampleuser/code/recall-skill",
      "installed_at": "2026-01-26T18:30:00",
      "files": [
        "bin/session-context.py",
        "bin/index-session.py",
        "bin/recall-sessions.py",
        "hooks/on-bash-failure.py",
        "lib/sops.py",
        "commands/recall.md"
      ],
      "migrations_run": ["v1.0.0_to_v1.1.0", "v1.1.0_to_v1.2.0"]
    }
  }
}
```

## Migration System

Migrations in `migrations/` with version-boundary naming:

```
migrations/
  v1.0.0_to_v1.1.0.py
  v1.1.0_to_v2.0.0.py
```

Standard migration interface:

```python
#!/usr/bin/env python3
"""Migration: Add tiered storage for recall index."""

VERSION_FROM = "1.0.0"
VERSION_TO = "1.1.0"

def check_needed() -> bool:
    """Return True if this migration should run."""
    ...

def migrate() -> bool:
    """Run the migration. Return True on success."""
    ...

def rollback() -> bool:
    """Undo the migration if possible."""
    ...

if __name__ == "__main__":
    if check_needed():
        migrate()
```

On upgrade, migrations between versions run in order.

## Commands

### skill install <path>

```
$ skill install ~/code/recall-skill

Installing recall v1.3.0...
  ✓ Copied bin/session-context.py
  ✓ Copied bin/index-session.py
  ✓ Copied bin/recall-sessions.py
  ✓ Copied hooks/on-bash-failure.py
  ✓ Copied lib/sops.py
  ✓ Registered 3 hooks in settings.json
  ✓ Installed recall v1.3.0
```

### skill upgrade <name>

```
$ skill upgrade recall

Upgrading recall 1.2.0 → 1.3.0...
  ✓ Running migration v1.2.0_to_v1.3.0
  ✓ Copied 4 files
  ✓ Upgraded recall to v1.3.0
```

### skill list

```
$ skill list

Installed skills:
  recall      1.3.0  ~/code/recall-skill
  core-utils  1.0.0  ~/code/core-utils
```

## Dependency Handling

**On install:** Fail if dependency not met:
```
Error: Missing dependency: core-utils>=1.0.0
  Install it first: skill install <path-to-core-utils>
```

**On upgrade:** Warn about dependents:
```
Note: These skills depend on core-utils:
  - recall (requires >=1.0.0) ✓ compatible
```

No automatic cascading - manual upgrades only.

## File Structure

```
~/.claude/
  bin/
    skill                 # CLI tool
    session-context.py    # installed files
    ...
  hooks/
    on-bash-failure.py
  lib/
    sops.py
  commands/
    recall.md
  skills.json             # state tracking

~/code/recall-skill/      # skill source
  SKILL.md
  bin/
  hooks/
  lib/
  commands/
  migrations/
    v1.0.0_to_v1.1.0.py
```

## Implementation

Single Python script `~/.claude/bin/skill` (~300 lines):
1. Parse SKILL.md frontmatter
2. Manage `skills.json` state
3. Copy files to correct locations
4. Update `settings.json` hooks
5. Run versioned migrations
