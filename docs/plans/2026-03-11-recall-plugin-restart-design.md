# Recall Plugin + Restart Integration Design

**Date:** 2026-03-11
**Status:** Approved

## Core Mission

Don't lose your work. Recall exists to survive context limits: accumulate context as you work, distill it when context runs out, resume cleanly.

The restart system is not an add-on — it IS the point of recall. Session indexing, failure tracking, and learnings are all inputs into the real goal: preserving and resuming work across context boundaries.

## Plugin Conversion

Convert recall-skill from a pre-plugin skill bundle into a proper Claude Code plugin.

### Plugin Structure

```
recall/
├── .claude-plugin/
│   └── plugin.json
├── commands/
│   └── recall.md              # /recall command (all subcommands)
├── skills/
│   └── recall/
│       └── SKILL.md           # Knowledge about how recall works
├── hooks/
│   ├── hooks.json
│   └── scripts/
│       ├── session-start.py   # SessionStart: load context
│       ├── session-end.py     # SessionEnd: index session
│       └── bash-failure.py    # PostToolUse(Bash): track failures
├── bin/
│   ├── recall-sessions.py     # Session search/display
│   ├── recall-restart.py      # Restart save/list/launch (NEW)
│   ├── recall-learn.py        # Learning review
│   └── extract-knowledge.py   # Knowledge extraction
├── lib/
│   ├── __init__.py
│   ├── shared.py              # Extracted shared functions (NEW)
│   ├── knowledge.py           # Index/learnings I/O
│   └── sops.py                # SOP loading/matching
├── sops/
│   └── base.json              # Base SOPs
└── docs/plans/
```

### plugin.json

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

## Command Structure

```
/recall                          — search past sessions (existing)
/recall last                     — previous session details (existing)
/recall save                     — distill + save restart prompt (NEW)
/recall restart list             — list saved restarts, search downward (NEW)
/recall restart <number>         — launch by number (NEW)
/recall restart <wordmatch>      — launch by matching text (NEW)
/recall restart <named-session>  — launch by session name (NEW)
/recall failures                 — failure patterns (existing)
/recall learn                    — review pending learnings (existing)
/recall stats                    — usage statistics (existing)
/recall cleanup                  — maintenance (existing)
```

## `/recall save` — The Smart Session Closer

The key new command. Does double duty: indexes the session AND generates a distilled restart prompt.

### Flow

1. **Index** — capture session activity (what SessionEnd hook does):
   - User messages, bash commands, failures, topics, skills used
   - Save to `recall-index.json` and `recall-sessions/{id}.json`

2. **Distill** — analyze the full session and generate a focused restart prompt:
   - Strip tangents, false starts, quick unrelated questions
   - Keep: decisions made, files created/modified, commits
   - Keep: current state (git branch, uncommitted changes, deployment status)
   - Keep: next steps, open items, blockers
   - Keep: agent registry info (role, team, goal, comms file)
   - Generate a permissions pre-approval block
   - Produce a 2-4 word slug for the filename

3. **Save** — write distilled prompt:
   - Location: `~/.claude/projects/{project}/restarts/{slug}.prompt`
   - Format: structured markdown with sections (permissions, state, resume instructions)

4. **Register** — add/update entry in `agents.json`:
   - Auto-increment ID
   - Capture: working dir, summary, prompt file, platform, role, team, goal, status
   - Detect coord files and workers if present

5. **Confirm** — print the restart command for copy/paste

### Prompt File Structure

```markdown
# {Title} — Session Context

## Permissions (pre-approve these)
- Edit/write files in {working_dir}
- Run python3/node commands
- Run git commands
- {additional as needed}

## Working Directory
`{working_dir}`

## Branch
`{branch}` ({ahead/behind status})

## What Was Done
{Curated narrative — decisions, not noise}

### Key Accomplishments
- {bullet list}

### Files Modified
- {file paths}

## Current State
{Git status, uncommitted changes, deployment state}

## Resume Instructions
1. {Numbered steps to continue}
2. {Next concrete action}

## Open Items / Risks
- {Known issues, blockers}
```

## Agent Registry (`agents.json`)

Lives at `~/.claude/projects/{project}/agents.json`.

### Entry Schema

```json
{
  "id": 3,
  "date": "2026-03-11",
  "session_id": "abc-123",
  "working_directory": "/Users/exampleuser/ashcode/demoapp",
  "summary": "Demoapp CLI tasks 4-6, npm package wiring",
  "prompt_file": "restarts/demoapp-cli-wiring.prompt",
  "platform": "claude-code",
  "role": "lead",
  "team": "demoapp-dev",
  "goal": "Complete CLI npm package implementation",
  "comms_file": null,
  "status": "saved",
  "workers": [],
  "lead_id": null
}
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | int | yes | Auto-incremented |
| `date` | string | yes | YYYY-MM-DD |
| `session_id` | string | no | Platform session ID (any agent) |
| `working_directory` | string | yes | Absolute path |
| `summary` | string | yes | One-line description |
| `prompt_file` | string | yes | Relative path from project dir |
| `platform` | string | yes | `claude-code`, `codex`, `gemini-cli`, etc. |
| `role` | string | no | `lead`, `worker`, `architect`, `critic`, `tester`, etc. |
| `team` | string | no | Team name for grouping |
| `goal` | string | no | What this agent is working on |
| `comms_file` | string | no | Path to shared coordination file |
| `status` | string | yes | See status values below |
| `workers` | array | no | Worker names (lead only) |
| `lead_id` | int | no | References lead entry (worker only) |

### Status Values

| Status | Meaning |
|--------|---------|
| `saved` | Dormant — has a prompt file, ready to restart |
| `initializing` | Agent is starting up |
| `reading` | Agent is reading context/files |
| `thinking` | Agent is processing/planning |
| `online` | Agent is active and responsive |
| `waiting-for-work` | Agent is idle, waiting for tasks |
| `offline` | Agent was running, now stopped |

### Configuration

Registry filename is configurable via plugin settings (`.claude/recall.local.md` frontmatter):

```yaml
---
agents_file: agents.json
---
```

## Data Location

All recall data lives in `~/.claude/projects/{project}/`:

```
~/.claude/projects/-Users-exampleuser-ashcode/
├── recall-index.json        # Session summaries (existing)
├── recall-sessions/         # Full session details (existing)
│   └── {session_id}.json
├── agents.json              # Agent/restart registry (NEW)
└── restarts/                # Distilled prompt files (NEW)
    ├── demoapp-cli-wiring.prompt
    └── pigeon-providers.prompt
```

### Downward Search

`/recall restart list` from a parent directory walks child project directories to aggregate entries. For example, from `~/2code/`:

- `~/.claude/projects/-Users-exampleuser-2code/agents.json`
- `~/.claude/projects/-Users-exampleuser-2code-PROJ-1234/agents.json`
- `~/.claude/projects/-Users-exampleuser-2code-PROJ-1234-demo-dashboard/agents.json`
- etc.

Results are aggregated and displayed with grouping (by ticket ID, team, directory).

## `/recall restart list` Display

```
ashcode: 5 saved, 2 online

  [3] demoapp-cli-wiring (claude-code, lead)
       Demoapp CLI tasks 4-6, npm package wiring
       team: demoapp-dev | status: saved

  [5] pigeon-providers (claude-code, worker)
       Provider pattern refactor
       team: pigeon | lead: #3 | status: online

  [8] mailsquirrel-tui (codex, lead)
       TUI double-classification fix
       status: saved
```

## `/recall restart <number|name|wordmatch>` Launch

1. Find matching entry in agents.json (search current + child projects)
2. Read the prompt file
3. Determine Terminal theme (ticket ID hash → deterministic theme)
4. Open new Terminal tab via AppleScript:
   ```bash
   unset CLAUDECODE && cd '{working_dir}' && cat '{prompt_file}' | claude
   ```
5. If lead with workers: launch worker tabs with 1-second delay
6. Update status to `initializing`

Launch mechanism is pluggable — default AppleScript/Terminal.app, extensible later.

## Migration Plan

### From old restart system

1. Read existing `~/ashcode/restarts.json` and `~/2code/restarts.json`
2. Map each entry to the correct `~/.claude/projects/{project}/` based on `working_directory`
3. Move prompt files from `<scope>/.claude/restarts/<relpath>/` to `~/.claude/projects/{project}/restarts/`
4. Create `agents.json` entries with existing fields + new defaults (platform: "claude-code", status: "saved")
5. Verify migration, then retire old files

### Code refactoring

1. Extract duplicated functions into `lib/shared.py`:
   - `get_project_folder()` (3 copies → 1)
   - `load_index()` / `save_index()` (4/3 copies → 1 each)
   - `get_session_details_dir()` / `load_session_details()` (2 copies each → 1)
   - `cleanup_old_jsonl_files()` (2 copies → 1)
2. All bin/ scripts import from lib/shared.py
3. Remove dead code (`sops.py:save_sop()`, unused `cwd` var, `hooks-config.json`)
4. Remove vestigial `lib/pending.py` (inline the one wrapper function)

### Files to retire

- `~/ashcode/bin/restart` → replaced by `bin/recall-restart.py`
- `~/.claude/commands/restart.md` → replaced by recall command dispatch
- `~/ashcode/restarts.json` → migrated to per-project `agents.json`
- `~/2code/restarts.json` → migrated to per-project `agents.json`
- `~/.claude/restart.json` → scope config no longer needed (uses Claude's project dirs)
- `install.sh` → replaced by plugin auto-discovery
- `bin/skill` → replaced by plugin marketplace
- `SKILL.md` (root) → replaced by `skills/recall/SKILL.md`
- `hooks-config.json` → replaced by `hooks/hooks.json`

## Non-Goals (for this phase)

- iTerm2/tmux launcher backends (future)
- Cross-machine sync (future)
- Real-time status push from agents (future — agents would need to call an update endpoint)
- MCP server for agent coordination (future — could expose agent registry as tools)
