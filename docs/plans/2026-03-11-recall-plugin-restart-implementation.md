# Recall Plugin + Restart Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert recall-skill into a proper Claude Code plugin and integrate restart/agent management as the core workflow.

**Architecture:** Extract shared code into `lib/shared.py`, convert to plugin structure (`.claude-plugin/plugin.json`), port restart logic from `~/ashcode/bin/restart` into `bin/recall-restart.py`, and unify data storage into `~/.claude/projects/{project}/`.

**Tech Stack:** Python 3, JSON, Bash (AppleScript for Terminal tab launching), Claude Code plugin system.

---

### Task 1: Create `lib/shared.py` — Extract Duplicated Functions

**Files:**
- Create: `lib/shared.py`
- Modify: `bin/recall-sessions.py` (remove duplicated functions, add imports)
- Modify: `bin/index-session.py` (remove duplicated functions, add imports)
- Modify: `hooks/on-bash-failure.py` (update imports if needed)
- Modify: `bin/session-context.py` (remove duplicated functions, add imports → this file becomes `hooks/scripts/session-start.py` in Task 3)
- Modify: `lib/knowledge.py` (remove duplicated functions, import from shared)
- Delete: `lib/pending.py` (inline the one wrapper function)

**Step 1: Create `lib/shared.py` with consolidated functions**

```python
"""Shared utilities for recall plugin."""

import json
import os
from pathlib import Path
from typing import Optional


def get_project_folder(cwd: str = None) -> str:
    """Convert working directory to Claude's project folder naming convention."""
    if cwd is None:
        cwd = os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()
    return cwd.replace('/', '-')


def get_project_dir(project_folder: str = None) -> Path:
    """Get the project directory path under ~/.claude/projects/."""
    if project_folder is None:
        project_folder = get_project_folder()
    return Path.home() / '.claude' / 'projects' / project_folder


def get_index_path(project_folder: str = None) -> Path:
    """Get path to recall-index.json."""
    return get_project_dir(project_folder) / 'recall-index.json'


def get_session_details_dir(project_folder: str = None) -> Path:
    """Get the directory for storing session detail files."""
    return get_project_dir(project_folder) / 'recall-sessions'


def get_restarts_dir(project_folder: str = None) -> Path:
    """Get the directory for storing restart prompt files."""
    d = get_project_dir(project_folder) / 'restarts'
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_agents_file(project_folder: str = None, filename: str = 'agents.json') -> Path:
    """Get path to agents registry file."""
    return get_project_dir(project_folder) / filename


def load_index(project_folder: str = None, create_if_missing: bool = False) -> Optional[dict]:
    """Load recall index.

    Args:
        project_folder: Project folder name. Auto-detected if None.
        create_if_missing: If True, return empty index structure instead of None.
    """
    if project_folder is None:
        project_folder = get_project_folder()
    index_file = get_index_path(project_folder)
    if index_file.exists():
        try:
            with open(index_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    if create_if_missing:
        return {
            'version': 2,
            'project': project_folder,
            'sessions': {},
            'failure_patterns': {},
            'learnings': [],
            'pending_learnings': [],
            'usage': {'skills': {}, 'learnings_shown': {}}
        }
    return None


def save_index(index: dict, project_folder: str = None, prune_fn=None):
    """Save recall index to disk.

    Args:
        index: The index dict.
        project_folder: Project folder name. Auto-detected if None.
        prune_fn: Optional function to prune index before saving (e.g., prune_index).
    """
    if project_folder is None:
        project_folder = get_project_folder()
    index_dir = get_project_dir(project_folder)
    index_dir.mkdir(parents=True, exist_ok=True)
    if prune_fn:
        index = prune_fn(index)
    index_file = index_dir / 'recall-index.json'
    with open(index_file, 'w') as f:
        json.dump(index, f, indent=2, default=str)


def load_session_details(project_folder: str, session_id: str) -> Optional[dict]:
    """Load full session details from separate file."""
    details_file = get_session_details_dir(project_folder) / f"{session_id}.json"
    if details_file.exists():
        try:
            with open(details_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None


def load_agents(project_folder: str = None, filename: str = 'agents.json') -> list:
    """Load agent registry entries."""
    agents_file = get_agents_file(project_folder, filename)
    if agents_file.exists():
        try:
            with open(agents_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []


def save_agents(agents: list, project_folder: str = None, filename: str = 'agents.json'):
    """Save agent registry entries."""
    agents_file = get_agents_file(project_folder, filename)
    agents_file.parent.mkdir(parents=True, exist_ok=True)
    with open(agents_file, 'w') as f:
        json.dump(agents, f, indent=2, default=str)
```

**Step 2: Update `lib/knowledge.py` to import from shared**

Replace `get_project_folder()`, `get_index_path()`, `load_index()`, `save_index()` with imports from `lib.shared`. Remove the local definitions. Keep knowledge-specific functions (`load_learnings`, `save_learning`, etc.) in place.

Key changes:
```python
# knowledge.py — replace local definitions with:
from .shared import get_project_folder, get_index_path, load_index, save_index
```

Remove lines 16-66 (the duplicated function definitions). Keep everything after.

**Step 3: Delete `lib/pending.py`**

This file is 20 lines and wraps a single function. Inline its usage wherever it's called (likely in `recall-learn.py`).

**Step 4: Update `bin/recall-sessions.py` to import from lib**

Add to top (after existing imports):
```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.shared import get_project_folder, get_session_details_dir, load_index, save_index, load_session_details
```

Remove lines 28-83 (the 5 duplicated function definitions: `get_project_folder`, `get_session_details_dir`, `load_session_details`, `load_index`, `save_index`).

**Step 5: Update `bin/index-session.py` to import from lib**

Add to top:
```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.shared import get_project_folder, get_session_details_dir, load_index, save_index, load_session_details
```

Remove lines 44-46 (`get_project_folder`), 49-51 (`get_session_details_dir`), 236-257 (`load_index`), 272-281 (`load_session_details`), 416-426 (`save_index`).

Note: `index-session.py`'s `save_index` calls `prune_index()` — pass it as `prune_fn`:
```python
save_index(index, project_folder, prune_fn=prune_index)
```

And its `load_index` returns a full structure — use `create_if_missing=True`:
```python
index = load_index(project_folder, create_if_missing=True)
```

**Step 6: Update `bin/session-context.py` to import from lib**

Add to top:
```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.shared import get_project_folder, load_index
```

Remove lines 13-27 (duplicated `get_project_folder` and `load_index`).

**Step 7: Verify all imports work**

Run from repo root:
```bash
cd ~/ashcode/recall-skill && python3 -c "from lib.shared import get_project_folder, load_index, save_index, get_session_details_dir, load_session_details, load_agents, save_agents; print('OK')"
```
Expected: `OK`

Run each bin script with `--help` or dry run to verify no import errors:
```bash
python3 bin/recall-sessions.py 2>&1 | head -5
python3 bin/session-context.py 2>&1 | head -5
```
Expected: Normal output (not ImportError)

**Step 8: Commit**

```bash
git add lib/shared.py lib/knowledge.py bin/recall-sessions.py bin/index-session.py bin/session-context.py
git rm lib/pending.py
git commit -m "refactor: extract shared functions into lib/shared.py, remove duplicates"
```

---

### Task 2: Convert to Plugin Structure

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `hooks/hooks.json`
- Move: `bin/session-context.py` → `hooks/scripts/session-start.py`
- Move: `bin/index-session.py` → `hooks/scripts/session-end.py`
- Move: `hooks/on-bash-failure.py` → `hooks/scripts/bash-failure.py`
- Create: `skills/recall/SKILL.md` (from existing root `SKILL.md`)
- Delete: `install.sh` (replaced by plugin auto-discovery)
- Delete: `bin/skill` (replaced by plugin marketplace)
- Delete: `hooks-config.json` (replaced by hooks/hooks.json)

**Step 1: Create `.claude-plugin/plugin.json`**

```bash
mkdir -p ~/ashcode/recall-skill/.claude-plugin
```

```json
{
  "name": "recall",
  "version": "2.0.0",
  "description": "Context survival across session limits. Accumulate, distill, resume.",
  "author": {
    "name": "ashrocket collective"
  },
  "repository": "https://github.com/ashrocket/recall-skill",
  "license": "MIT",
  "keywords": ["session", "restart", "context", "memory", "agent"]
}
```

**Step 2: Create `hooks/hooks.json`**

```json
{
  "hooks": [
    {
      "event": "SessionStart",
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session-start.py",
        "timeout": 5
      }]
    },
    {
      "event": "SessionEnd",
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session-end.py",
        "timeout": 30
      }]
    },
    {
      "event": "PostToolUse",
      "matcher": "Bash",
      "hooks": [{
        "type": "command",
        "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/bash-failure.py",
        "timeout": 10
      }]
    }
  ]
}
```

**Step 3: Move hook scripts to `hooks/scripts/`**

```bash
mkdir -p ~/ashcode/recall-skill/hooks/scripts
cp bin/session-context.py hooks/scripts/session-start.py
cp bin/index-session.py hooks/scripts/session-end.py
cp hooks/on-bash-failure.py hooks/scripts/bash-failure.py
```

Update the `sys.path.insert` in each moved file — the relative path to `lib/` changes:
```python
# In hooks/scripts/*.py, the path to lib/ is:
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from lib.shared import get_project_folder, load_index
```

**Step 4: Create `skills/recall/SKILL.md`**

```bash
mkdir -p ~/ashcode/recall-skill/skills/recall
```

```markdown
---
name: recall
description: This skill should be used when the user asks to "save session", "restart session", "recall previous work", "list saved sessions", "resume where I left off", "save my progress", or mentions context limits, session management, or agent coordination. Provides session persistence, intelligent restart, and multi-agent registry.
version: 2.0.0
---

# Recall — Context Survival

Recall preserves session context across context limits. Three phases:

1. **Accumulate** — hooks capture session activity (commands, failures, learnings)
2. **Distill** — `/recall save` compresses: strip tangents, keep decisions and state
3. **Resume** — `/recall restart` feeds the briefing back, resume without noise

## Commands

- `/recall` — search past sessions
- `/recall last` — previous session details
- `/recall save` — distill + save restart prompt (smart session closer)
- `/recall restart list` — list saved restarts (searches downward through child projects)
- `/recall restart <number>` — launch by number
- `/recall restart <text>` — launch by word match in summary/prompt
- `/recall failures` — failure patterns and SOPs
- `/recall learn` — review pending learnings

## `/recall save` Behavior

When invoked, `/recall save` performs:
1. Index the session (what SessionEnd hook does)
2. Distill: analyze full session, strip noise/tangents/false-starts, keep decisions + state
3. Write focused restart prompt to project restarts directory
4. Register in agent registry with metadata (platform, role, team, goal, status)
5. Print restart command

The distilled prompt should be a clean briefing, not a transcript dump. Remove unrelated quick questions, failed approaches, and detritus.

## Agent Registry

Each saved/running agent is tracked with: id, session_id, working_directory, summary, prompt_file, platform (claude-code/codex/gemini-cli), role (lead/worker/architect/etc.), team, goal, comms_file, status (saved/initializing/reading/thinking/online/waiting-for-work/offline), workers list, lead_id.
```

**Step 5: Remove obsolete files**

```bash
rm install.sh bin/skill hooks-config.json
```

Keep the root `SKILL.md` for now (migration reference) but it won't be auto-discovered since the plugin system looks in `skills/*/SKILL.md`.

**Step 6: Verify plugin structure**

```bash
ls -la .claude-plugin/plugin.json hooks/hooks.json skills/recall/SKILL.md commands/recall.md
```
Expected: All files exist.

**Step 7: Commit**

```bash
git add .claude-plugin/plugin.json hooks/hooks.json hooks/scripts/ skills/recall/SKILL.md
git rm install.sh bin/skill hooks-config.json
git commit -m "feat: convert to proper Claude Code plugin structure"
```

---

### Task 3: Update `commands/recall.md` — Add Restart Subcommands

**Files:**
- Modify: `commands/recall.md`

**Step 1: Read current `commands/recall.md`**

Read the file to understand current dispatch logic.

**Step 2: Add restart subcommand dispatch**

Add these cases to the command's dispatch logic:

```markdown
## Subcommands

### save
Distill and save the current session as a restart prompt.

1. Run session indexing: `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session-end.py`
2. Analyze the full conversation and distill it:
   - Strip tangents, false starts, unrelated quick questions
   - Keep: decisions made, files created/modified, commits made
   - Keep: current state (git branch, uncommitted changes)
   - Keep: next steps, open items, blockers
3. Generate a 2-4 word slug from the summary (lowercase, hyphenated)
4. Write the distilled prompt to the restarts directory:
   `python3 ${CLAUDE_PLUGIN_ROOT}/bin/recall-restart.py save "$(pwd)" "<summary>" --prompt-file "<slug>.prompt"`
5. Print: "Session saved. Restart with: /recall restart <number>"

### restart list
List all saved restart entries for the current project and child projects.
Run: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/recall-restart.py list`

### restart <number>
Launch a saved restart by entry number.
Run: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/recall-restart.py launch <number>`

### restart <text>
Search for and launch a restart matching the given text.
Run: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/recall-restart.py match "<text>"`
```

**Step 3: Commit**

```bash
git add commands/recall.md
git commit -m "feat: add save and restart subcommands to /recall"
```

---

### Task 4: Create `bin/recall-restart.py` — Core Restart Logic

**Files:**
- Create: `bin/recall-restart.py`

This is the big one. Port logic from `~/ashcode/bin/restart` (bash+python) into pure Python.

**Step 1: Write `bin/recall-restart.py`**

```python
#!/usr/bin/env python3
"""Recall restart management — save, list, launch, match agent sessions."""

import sys
import os
import json
import re
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.shared import (
    get_project_folder, get_project_dir, get_restarts_dir,
    load_agents, save_agents, load_index
)

# Terminal themes for visual grouping
THEMES = ['Ocean', 'Homebrew', 'Night Owl', 'Gruvbox-Dark',
          'Nord', 'Cobalt2', 'Catppuccin-Mocha', 'Mariana']

ANSI = ['\033[36m', '\033[32m', '\033[35m', '\033[33m',
        '\033[34m', '\033[96m', '\033[95m', '\033[93m']
RESET = '\033[0m'


def get_ticket_ids(text: str) -> set:
    """Extract ticket IDs (e.g., PROJ-1234) from text."""
    return set(re.findall(r'[A-Z]+-\d+', text[:500]))


def union_find_groups(entries: list) -> dict:
    """Group entries by shared ticket IDs using union-find."""
    n = len(entries)
    par = list(range(n))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            par[b] = a

    # Collect IDs per entry
    all_ids = []
    for e in entries:
        ids = get_ticket_ids(e.get('summary', ''))
        # Add directory-based ID
        wd = e.get('working_directory', '')
        parts = wd.rstrip('/').split('/')
        if parts:
            ids.add(f'dir:{parts[-1]}')
        # Read prompt file for more IDs (first 500 chars)
        pf = e.get('prompt_file', '')
        if pf:
            project_folder = get_project_folder(wd)
            prompt_path = get_project_dir(project_folder) / pf
            if prompt_path.exists():
                try:
                    with open(prompt_path, 'r') as f:
                        ids |= get_ticket_ids(f.read(500))
                except IOError:
                    pass
        all_ids.append(ids)

    # Union entries with shared IDs
    for i in range(n):
        for j in range(i + 1, n):
            if all_ids[i] & all_ids[j]:
                union(i, j)

    # Build groups
    groups = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)

    return groups


def get_theme(ids: set, entry: dict) -> tuple:
    """Deterministic theme from ticket IDs."""
    tickets = sorted(ids - {i for i in ids if i.startswith('dir:')})
    key = tickets[0] if tickets else entry.get('working_directory', 'default')
    idx = int(hashlib.md5(key.encode()).hexdigest(), 16) % len(THEMES)
    return THEMES[idx], ANSI[idx]


def find_child_projects(project_folder: str) -> list:
    """Find child project folders for downward search."""
    projects_dir = Path.home() / '.claude' / 'projects'
    if not projects_dir.exists():
        return []
    prefix = project_folder
    children = []
    for d in projects_dir.iterdir():
        if d.is_dir() and d.name.startswith(prefix) and d.name != project_folder:
            children.append(d.name)
    return children


def cmd_save(args):
    """Save a new agent/restart entry."""
    if len(args) < 2:
        print("Usage: recall-restart.py save <working_dir> <summary> [--prompt-file FILE] [--platform PLATFORM] [--role ROLE] [--team TEAM] [--goal GOAL] [--comms-file PATH] [--session-id ID]", file=sys.stderr)
        sys.exit(1)

    working_dir = args[0]
    summary = args[1]
    project_folder = get_project_folder(working_dir)

    # Parse optional flags
    opts = {}
    i = 2
    while i < len(args):
        if args[i] == '--prompt-file' and i + 1 < len(args):
            opts['prompt_file'] = args[i + 1]; i += 2
        elif args[i] == '--platform' and i + 1 < len(args):
            opts['platform'] = args[i + 1]; i += 2
        elif args[i] == '--role' and i + 1 < len(args):
            opts['role'] = args[i + 1]; i += 2
        elif args[i] == '--team' and i + 1 < len(args):
            opts['team'] = args[i + 1]; i += 2
        elif args[i] == '--goal' and i + 1 < len(args):
            opts['goal'] = args[i + 1]; i += 2
        elif args[i] == '--comms-file' and i + 1 < len(args):
            opts['comms_file'] = args[i + 1]; i += 2
        elif args[i] == '--session-id' and i + 1 < len(args):
            opts['session_id'] = args[i + 1]; i += 2
        elif args[i] == '--lead-id' and i + 1 < len(args):
            opts['lead_id'] = int(args[i + 1]); i += 2
        elif args[i] == '--workers' and i + 1 < len(args):
            opts['workers'] = args[i + 1].split(','); i += 2
        else:
            i += 1

    # Also check env vars (backward compat with old restart system)
    if 'prompt_file' not in opts:
        opts['prompt_file'] = os.environ.get('RESTART_PROMPT_FILE', '')
    if 'role' not in opts and os.environ.get('RESTART_ROLE'):
        opts['role'] = os.environ['RESTART_ROLE']
    if 'lead_id' not in opts and os.environ.get('RESTART_LEAD'):
        opts['lead_id'] = int(os.environ['RESTART_LEAD'])
    if os.environ.get('RESTART_WORKER_NAME'):
        opts.setdefault('team', os.environ['RESTART_WORKER_NAME'])
    if os.environ.get('RESTART_WORKERS'):
        opts.setdefault('workers', os.environ['RESTART_WORKERS'].split(','))

    # Load existing entries and compute next ID
    agents = load_agents(project_folder)
    next_id = max((e.get('id', 0) for e in agents), default=0) + 1

    # Build entry
    entry = {
        'id': next_id,
        'date': datetime.now().strftime('%Y-%m-%d'),
        'session_id': opts.get('session_id', ''),
        'working_directory': working_dir,
        'summary': summary,
        'prompt_file': opts.get('prompt_file', ''),
        'platform': opts.get('platform', 'claude-code'),
        'role': opts.get('role', 'lead'),
        'team': opts.get('team', ''),
        'goal': opts.get('goal', ''),
        'comms_file': opts.get('comms_file', ''),
        'status': 'saved',
        'workers': opts.get('workers', []),
        'lead_id': opts.get('lead_id', None),
    }

    agents.append(entry)
    save_agents(agents, project_folder)

    print(f"Saved as #{next_id}. Restart with: /recall restart {next_id}")


def cmd_list(args):
    """List saved restart entries with grouping."""
    cwd = os.getcwd()
    project_folder = get_project_folder(cwd)

    # Gather entries from current + child projects
    all_entries = []
    folders = [project_folder] + find_child_projects(project_folder)

    for pf in folders:
        entries = load_agents(pf)
        for e in entries:
            e['_project'] = pf
        all_entries.extend(entries)

    if not all_entries:
        print("No saved restarts found.")
        return

    # Separate leads and workers
    leads = [e for e in all_entries if e.get('role') != 'worker']
    workers = [e for e in all_entries if e.get('role') == 'worker']
    worker_map = {}
    for w in workers:
        lead_id = w.get('lead_id')
        if lead_id is not None:
            worker_map.setdefault(lead_id, []).append(w)

    # Group leads
    if leads:
        groups = union_find_groups(leads)
    else:
        groups = {}

    saved = sum(1 for e in all_entries if e.get('status') == 'saved')
    online = sum(1 for e in all_entries if e.get('status') not in ('saved', 'offline', ''))

    print(f"{len(all_entries)} entries ({saved} saved, {online} online)\n")

    group_idx = 0
    for root, indices in sorted(groups.items(), key=lambda x: x[0]):
        group_entries = [leads[i] for i in indices]
        ids = set()
        for e in group_entries:
            ids |= get_ticket_ids(e.get('summary', ''))
        theme_name, ansi = get_theme(ids, group_entries[0])

        print(f"  {ansi}--- {theme_name} ---{RESET}")
        for e in group_entries:
            status_str = f" | status: {e.get('status', 'saved')}" if e.get('status', 'saved') != 'saved' else ''
            team_str = f" | team: {e.get('team')}" if e.get('team') else ''
            role_str = f" ({e.get('platform', 'claude-code')}, {e.get('role', 'lead')})"
            print(f"  {ansi}[{e['id']}]{RESET} {e.get('summary', '(no summary)')}{role_str}")
            print(f"       {e.get('working_directory', '')}{team_str}{status_str}")

            # Show workers nested under this lead
            for w in worker_map.get(e['id'], []):
                w_status = f" [{w.get('status', 'saved')}]" if w.get('status', 'saved') != 'saved' else ''
                print(f"       └─ [{w['id']}] worker:{w.get('team', '?')} — {w.get('summary', '')}{w_status}")
        print()
        group_idx += 1


def cmd_launch(args):
    """Launch a restart by entry number."""
    if not args:
        print("Usage: recall-restart.py launch <number>", file=sys.stderr)
        sys.exit(1)

    target_id = int(args[0])
    cwd = os.getcwd()
    project_folder = get_project_folder(cwd)

    # Search current + child projects
    folders = [project_folder] + find_child_projects(project_folder)
    entry = None
    entry_pf = None
    for pf in folders:
        for e in load_agents(pf):
            if e.get('id') == target_id:
                entry = e
                entry_pf = pf
                break
        if entry:
            break

    if not entry:
        print(f"Entry #{target_id} not found.", file=sys.stderr)
        sys.exit(1)

    _launch_entry(entry, entry_pf)

    # Launch workers if this is a lead
    if entry.get('role') != 'worker' and entry.get('workers'):
        for pf in folders:
            for e in load_agents(pf):
                if e.get('role') == 'worker' and e.get('lead_id') == target_id:
                    import time
                    time.sleep(1)
                    _launch_entry(e, pf)


def cmd_match(args):
    """Launch a restart by text match in summary or prompt file."""
    if not args:
        print("Usage: recall-restart.py match <text>", file=sys.stderr)
        sys.exit(1)

    query = ' '.join(args).lower()
    cwd = os.getcwd()
    project_folder = get_project_folder(cwd)

    folders = [project_folder] + find_child_projects(project_folder)
    matches = []
    for pf in folders:
        for e in load_agents(pf):
            if query in e.get('summary', '').lower():
                matches.append((e, pf))
                continue
            # Check prompt file content
            pfile = e.get('prompt_file', '')
            if pfile:
                prompt_path = get_project_dir(pf) / pfile
                if prompt_path.exists():
                    try:
                        with open(prompt_path, 'r') as f:
                            if query in f.read().lower():
                                matches.append((e, pf))
                    except IOError:
                        pass

    if not matches:
        print(f"No restart matching '{query}' found.", file=sys.stderr)
        sys.exit(1)

    if len(matches) == 1:
        _launch_entry(matches[0][0], matches[0][1])
    else:
        print(f"Multiple matches for '{query}':")
        for e, pf in matches:
            print(f"  [{e['id']}] {e.get('summary', '')}")
        print(f"\nUse: recall-restart.py launch <number>")


def _launch_entry(entry: dict, project_folder: str):
    """Open a Terminal tab and launch the restart."""
    wd = entry.get('working_directory', os.getcwd())
    prompt_file = entry.get('prompt_file', '')

    if not prompt_file:
        print(f"Entry #{entry['id']} has no prompt file.", file=sys.stderr)
        return

    prompt_path = get_project_dir(project_folder) / prompt_file
    if not prompt_path.exists():
        print(f"Prompt file not found: {prompt_path}", file=sys.stderr)
        return

    # Build terminal command
    team = entry.get('team', '')
    team_export = f"export CLAUDE_TEAM='{team}' && " if team else ''
    cmd = f"{team_export}unset CLAUDECODE && cd '{wd}' && cat '{prompt_path}' | claude"

    # Get theme
    ids = get_ticket_ids(entry.get('summary', ''))
    theme_name, _ = get_theme(ids, entry)

    # AppleScript to open Terminal tab
    applescript = f'''
    tell application "Terminal"
        activate
        tell application "System Events" to keystroke "t" using command down
        delay 0.3
        do script "{cmd}" in selected tab of front window
        set current settings of selected tab of front window to settings set "{theme_name}"
    end tell
    '''

    subprocess.run(['osascript', '-e', applescript], check=False)
    print(f"Launched #{entry['id']}: {entry.get('summary', '')} ({theme_name})")


def main():
    if len(sys.argv) < 2:
        print("Usage: recall-restart.py <save|list|launch|match> [args...]", file=sys.stderr)
        sys.exit(1)

    action = sys.argv[1]
    args = sys.argv[2:]

    if action == 'save':
        cmd_save(args)
    elif action == 'list':
        cmd_list(args)
    elif action == 'launch':
        cmd_launch(args)
    elif action == 'match':
        cmd_match(args)
    else:
        print(f"Unknown action: {action}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
```

**Step 2: Make executable**

```bash
chmod +x bin/recall-restart.py
```

**Step 3: Test basic operations**

```bash
cd ~/ashcode/recall-skill
python3 bin/recall-restart.py list
```
Expected: `0 entries (0 saved, 0 online)` or entries if agents.json exists.

```bash
python3 bin/recall-restart.py save "$(pwd)" "Test save entry" --prompt-file "restarts/test.prompt" --platform claude-code --role lead
```
Expected: `Saved as #1. Restart with: /recall restart 1`

```bash
python3 bin/recall-restart.py list
```
Expected: Shows the entry just created.

**Step 4: Commit**

```bash
git add bin/recall-restart.py
git commit -m "feat: add recall-restart.py — save, list, launch, match commands"
```

---

### Task 5: Write Migration Script

**Files:**
- Create: `migrations/v1_to_v2_restart.py`

**Step 1: Write migration script**

```python
#!/usr/bin/env python3
"""Migrate restart data from old scope-based system to recall plugin project dirs."""

import json
import os
import shutil
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.shared import get_project_folder, get_project_dir, load_agents, save_agents


def migrate_scope(scope_dir: str):
    """Migrate restarts.json and prompt files from a scope directory."""
    scope_path = Path(scope_dir).expanduser()
    restarts_json = scope_path / 'restarts.json'

    if not restarts_json.exists():
        print(f"  No restarts.json in {scope_path}, skipping.")
        return 0

    with open(restarts_json, 'r') as f:
        entries = json.load(f)

    print(f"  Found {len(entries)} entries in {restarts_json}")
    migrated = 0

    for entry in entries:
        wd = entry.get('working_directory', '')
        if not wd:
            print(f"    Skipping entry #{entry.get('number', '?')}: no working_directory")
            continue

        project_folder = get_project_folder(wd)
        project_dir = get_project_dir(project_folder)
        restarts_dir = project_dir / 'restarts'
        restarts_dir.mkdir(parents=True, exist_ok=True)

        # Find and copy prompt file
        prompt_filename = entry.get('prompt_file', 'restart.prompt')
        if entry.get('worker_name') and not entry.get('prompt_file'):
            prompt_filename = f"restart-{entry['worker_name']}.prompt"

        # Compute old prompt file location
        rel_path = os.path.relpath(wd, str(scope_path))
        old_restarts_dir = scope_path / '.claude' / 'restarts' / rel_path
        old_prompt = old_restarts_dir / prompt_filename

        new_prompt_rel = f"restarts/{prompt_filename}"
        new_prompt_abs = project_dir / new_prompt_rel

        if old_prompt.exists() and not new_prompt_abs.exists():
            shutil.copy2(str(old_prompt), str(new_prompt_abs))
            print(f"    Copied prompt: {old_prompt} → {new_prompt_abs}")

        # Build new agent entry
        agent_entry = {
            'id': entry.get('number', 0),
            'date': entry.get('date', ''),
            'session_id': '',
            'working_directory': wd,
            'summary': entry.get('summary', ''),
            'prompt_file': new_prompt_rel if new_prompt_abs.exists() else '',
            'platform': 'claude-code',
            'role': entry.get('role', 'lead'),
            'team': entry.get('worker_name', ''),
            'goal': '',
            'comms_file': entry.get('coord_file', ''),
            'status': 'saved',
            'workers': entry.get('workers', []),
            'lead_id': entry.get('lead', None),
        }

        # Load existing agents for this project and append
        agents = load_agents(project_folder)

        # Check for duplicate ID
        if any(a.get('id') == agent_entry['id'] for a in agents):
            # Reassign ID
            agent_entry['id'] = max((a.get('id', 0) for a in agents), default=0) + 1

        agents.append(agent_entry)
        save_agents(agents, project_folder)
        migrated += 1
        print(f"    Migrated #{agent_entry['id']}: {agent_entry['summary'][:60]}")

    return migrated


def main():
    import sys
    # Load old scope config
    config_file = Path.home() / '.claude' / 'restart.json'
    if config_file.exists():
        with open(config_file, 'r') as f:
            config = json.load(f)
        scopes = config.get('directories', [])
    else:
        scopes = ['~/2code', '~/ashcode']

    print("Migrating restart data to recall plugin format...\n")
    total = 0
    for scope in scopes:
        print(f"Scope: {scope}")
        total += migrate_scope(scope)
        print()

    print(f"Done. Migrated {total} entries total.")

    if '--cleanup' in sys.argv:
        print("\nOld files NOT deleted (manual cleanup recommended):")
        for scope in scopes:
            scope_path = Path(scope).expanduser()
            print(f"  rm {scope_path}/restarts.json")
            print(f"  rm -rf {scope_path}/.claude/restarts/")
        print(f"  rm {Path.home() / '.claude' / 'restart.json'}")
        print(f"  rm {Path.home() / '.claude' / 'commands' / 'restart.md'}")


if __name__ == '__main__':
    main()
```

**Step 2: Test migration (dry run)**

```bash
python3 migrations/v1_to_v2_restart.py
```
Expected: Lists entries being migrated, copies prompt files, creates agents.json entries.

**Step 3: Verify migrated data**

```bash
python3 bin/recall-restart.py list
```
Expected: Shows migrated entries with correct grouping.

**Step 4: Commit**

```bash
git add migrations/v1_to_v2_restart.py
git commit -m "feat: add migration script for old restart data to recall plugin format"
```

---

### Task 6: Clean Up Dead Code and Obsolete Files

**Files:**
- Modify: `lib/sops.py` — remove dead `save_sop()` function (lines 88-118)
- Delete: `bin/session-context.py` (moved to `hooks/scripts/session-start.py` in Task 2)
- Delete: `hooks/on-bash-failure.py` (moved to `hooks/scripts/bash-failure.py` in Task 2)
- Keep but deprecate: root `SKILL.md` (add deprecation notice pointing to `skills/recall/SKILL.md`)

**Step 1: Remove `save_sop()` from `lib/sops.py`**

Read `lib/sops.py`, find the `save_sop()` function (never called), and remove it.

**Step 2: Remove old hook/script locations**

```bash
git rm bin/session-context.py hooks/on-bash-failure.py
```

Only do this AFTER confirming `hooks/scripts/` copies are working (from Task 2).

**Step 3: Add deprecation notice to root SKILL.md**

Add to top of root `SKILL.md`:
```markdown
> **DEPRECATED**: This file is superseded by `skills/recall/SKILL.md`. This plugin now uses the Claude Code plugin system — see `.claude-plugin/plugin.json`.
```

**Step 4: Remove `bin/claude-history` and `commands/history.md` if they duplicate `commands/recall.md` history subcommand**

Check if `/recall history` or `/history` is the intended command. If `/recall` already handles history via its existing subcommands, the standalone `/history` command is redundant. Remove only if confirmed.

**Step 5: Commit**

```bash
git add -u
git commit -m "chore: remove dead code, deprecate old SKILL.md, clean up moved files"
```

---

### Task 7: Integration Test — Full Workflow

**Files:** None (testing only)

**Step 1: Verify plugin auto-discovery**

```bash
# Check plugin structure is valid
ls .claude-plugin/plugin.json commands/ skills/recall/SKILL.md hooks/hooks.json
```
Expected: All exist.

**Step 2: Test `/recall save` flow manually**

Simulate what the command does:
```bash
cd ~/ashcode/recall-skill

# 1. Run session indexing
python3 hooks/scripts/session-end.py 2>&1 | tail -5

# 2. Save a restart entry
python3 bin/recall-restart.py save "$(pwd)" "Integration test — plugin conversion complete" \
  --prompt-file "restarts/integration-test.prompt" \
  --platform claude-code \
  --role lead \
  --team recall-dev

# 3. List
python3 bin/recall-restart.py list

# 4. Match
python3 bin/recall-restart.py match "integration"
```

**Step 3: Test downward search**

```bash
# From parent directory
cd ~/ashcode
python3 ~/ashcode/recall-skill/bin/recall-restart.py list
```
Expected: Shows entries from ashcode project AND child projects.

**Step 4: Verify no import errors across all entry points**

```bash
python3 -c "import sys; sys.path.insert(0, '.'); from lib.shared import *; print('shared OK')"
python3 -c "import sys; sys.path.insert(0, '.'); from lib.knowledge import *; print('knowledge OK')"
python3 bin/recall-sessions.py 2>&1 | head -3
python3 bin/recall-restart.py list
python3 hooks/scripts/session-start.py 2>&1 | head -3
```
Expected: No ImportError for any of these.

**Step 5: Commit final state**

```bash
git add -A
git commit -m "test: verify full integration of recall plugin + restart"
```

---

### Task 8: Update MEMORY.md

**Files:**
- Modify: `~/.claude/projects/-Users-exampleuser-ashcode/memory/MEMORY.md`

**Step 1: Update recall-skill section**

Update the recall-skill entry in MEMORY.md to reflect:
- Now a proper plugin (has `.claude-plugin/plugin.json`)
- Restart integrated as `/recall save` + `/recall restart`
- Agent registry in `agents.json`
- Version bumped to 2.0.0
- Old restart system retired (mark `~/ashcode/bin/restart` and `~/.claude/commands/restart.md` as obsolete)

**Step 2: Commit memory update**

Not committed to recall-skill repo — this is in the memory directory.
