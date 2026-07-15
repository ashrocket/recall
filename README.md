<div align="center">

```
 ██████╗ ███████╗ ██████╗ █████╗ ██╗     ██╗
 ██╔══██╗██╔════╝██╔════╝██╔══██╗██║     ██║
 ██████╔╝█████╗  ██║     ███████║██║     ██║
 ██╔══██╗██╔══╝  ██║     ██╔══██║██║     ██║
 ██║  ██║███████╗╚██████╗██║  ██║███████╗███████╗
 ╚═╝  ╚═╝╚══════╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚══════╝
```

**Consistent context across work sessions.**

`Accumulate → Extract → Restart`

[![Version](https://img.shields.io/badge/version-3.4.0-f0a050?style=flat-square&labelColor=12151e)](https://github.com/ashrocket/recall)
[![License](https://img.shields.io/badge/license-MIT-56b6c2?style=flat-square&labelColor=12151e)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Claude%20Code%20%7C%20Codex%20%7C%20Gemini%20CLI-98c379?style=flat-square&labelColor=12151e)](https://github.com/ashrocket/recall)

</div>

---

When your AI coding agent hits its context limit, work stops. recall captures what happened, extracts the useful signals into a clean briefing, and lets you restart a new session with full context — no ten-minute re-briefs.

**One skill. `/recall` with subcommands.**

| Subcommand | What it does |
|------------|--------------|
| `/recall` | List recent sessions |
| `/recall list` | List recent sessions explicitly |
| `/recall last` | Show details from the most recent previous session |
| `/recall <term>` | Ranked local search; supports quoted literal fragments like `/recall '.p8'` and slash-delimited regex like `/recall /.*\.p8/` |
| `/recall save` | Locally extract the current session into a restart prompt |
| `/recall restart` | List saved named restarts; `restart summary` reviews a compact list; `restart <n>`, `<name>`, or `<text>` loads one; `restart --launch <n|text>` opens a separate window; `restart delete <n|text>` prunes old prompts |
| `/recall failures` | Bash failure patterns and SOPs |
| `/recall learn` | Review and approve pending learnings |
| `/recall knowledge` | Show current CLAUDE.md (global and project) |
| `/recall stats` | Skill and learning usage statistics |
| `/recall cleanup` | Analyze and prune the session index |
| `/recall help` | Show command help |

Hooks run on `SessionStart`, `SessionEnd`, and `PostToolUse:Bash`.

---

## Quick Start

```bash
# Claude Code (recommended)
/plugin marketplace add ashrocket/recall

# Codex CLI / Gemini CLI
git clone https://github.com/ashrocket/recall ~/.recall
# then copy AGENTS.md (Codex) or GEMINI.md (Gemini) from this repo
# Codex plugin installs use .codex-plugin/plugin.json and expose
# skills/recall/SKILL.md as the plugin skill.
```

**Full walkthrough:** [recall.pages.dev/start.html](https://recall.pages.dev/start.html) — 3-minute speedrun (install → save → restart) plus a 4-minute tour of every `/recall` subcommand.

---

## The Core Loop

The killer feature is `save` + `restart`. When context runs low:

```
user@mac ~/myapp > /recall save

  Indexing session...
  ✓ 47 messages · 12 commands · 2 failures captured
  ✓ Ranking session signals locally...
  ✓ Saved → recall-restarts/payroll-bonus-fix.prompt

  Restart with: /recall restart 1
```

Open a new session:

```
user@mac ~/myapp > /recall restart 1

  Loading payroll-bonus-fix...

  Branch:   feature/payroll-fix (2 commits ahead of main)
  Modified: src/payroll/bonus.ts
            tests/bonus.test.ts
  Next:     Fix rounding edge case on line 247, run test suite
  Risks:    Confirm % vs flat-rate behavior with product team

  ✓ Context restored. Continuing work...
```

`/recall save` is not a transcript dump. It uses local parsers and extractive TF-IDF ranking to write the registered restart briefing from indexed user messages, commands, failures, paths, and current git state. During the current A/B period, it also asks the LLM for a comparison candidate and logs which summary was better in `recall-save-evals.jsonl`. `/recall <term>` uses local ranking to return compact top matches, so broad search output does not need LLM triage.

Search is forgiving for day-to-day memory lookup: `/recall sops ?` ignores the standalone question mark, `/recall '.p8'` strips outer quotes and searches literally, and slash-delimited regex queries like `/recall /.*\.p8/` search the same indexed summaries, messages, commands, failures, and skills. `/recall /*\.p8/` is accepted as shorthand for the common "anything ending in .p8" pattern.

---

## /recall — Session Memory

```bash
/recall                    # list recent sessions with summaries
/recall list               # list recent sessions with summaries
/recall last               # full details from the previous session
/recall <term>             # ranked local search across past sessions
/recall '.p8'              # literal search for a token or filename fragment
/recall /.*\.p8/           # regex search
/recall failures           # failure patterns and learnings
/recall save               # locally extract + save session as restart prompt
/recall restart            # list saved named restart prompts
/recall restart summary    # compact numbered review list
/recall restart 3          # load restart #3
/recall restart payroll    # load an exact named restart when available
/recall restart latency    # search restarts by text match
/recall restart --launch 3 # open restart #3 in a separate window
/recall restart delete 3   # delete restart #3 and its stored prompt file
/recall learn              # review and approve pending learnings
/recall learn --batch      # accept all pending learnings
/recall cleanup --all      # clean noise, sensitive data, old files
/recall stats              # skill and learning usage stats
/recall knowledge          # show CLAUDE.md contents
/recall help               # show command help
```

### Example: searching past sessions

```
user@mac ~/myapp > /recall authentication

  Searching 51 sessions...

  3 matches for "authentication"

  2026-03-14  JWT migration, tests passing
              → src/auth/middleware.ts, guards.ts
              → "use RS256, not HS256 for multi-service"

  2026-03-09  Session timeout edge case
              → Fixed: extend on activity, not hard limit
              → middleware.ts line 88

  2026-02-28  OAuth2 flow setup
              → callback URL must exactly match env var
              → OAUTH_REDIRECT_URI in .env.local
```

### Example: session list

```
user@mac ~/myapp > /recall

  Recent sessions — myapp (51 total)

  today       payroll-bonus-fix     12 msgs  3 cmds   0 failures
  2026-03-19  auth-flow-refactor    34 msgs  18 cmds  1 failure
  2026-03-18  api-rate-limiting     28 msgs  22 cmds  4 failures
  2026-03-17  onboarding-ui         19 msgs  8 cmds   0 failures
  2026-03-14  jwt-migration         47 msgs  31 cmds  2 failures
```

---

## /recall failures — Bash SOPs

When a bash command fails, recall checks it against known error patterns and fires immediately:

```
$ git push origin feature/auth
  ERROR: remote: Permission to repo.git denied
  fatal: unable to access 'https://github.com/'

  ─── recall SOP: git_error ──────────────────────────────────
  You've hit this 3 times this month.
  Last command that worked:
    $ git remote set-url origin git@github.com:yourorg/repo.git
  Switch HTTPS → SSH. HTTPS tokens expire; SSH keys don't.
  ─────────────────────────────────────────────────────────────

$ git remote set-url origin git@github.com:yourorg/repo.git
$ git push origin feature/auth
  ✓ Branch pushed successfully
```

`/recall failures` also rolls up those errors across indexed sessions and shows approved learnings before recent failure groups.

**Failure categories tracked automatically:**

| Category | Triggers on |
|----------|-------------|
| `permission_denied` | "permission denied", "access denied", EACCES |
| `not_found` | "not found", "no such file", ENOENT |
| `git_error` | "fatal:", git remote errors |
| `connection_error` | "connection refused", "timeout" |
| `import_error` | "ImportError", "ModuleNotFoundError" |
| `syntax_error` | "SyntaxError", "parse error" |
| `npm_error` | "npm ERR", package install failures |
| `python_error` | "Traceback", unhandled exceptions |

```bash
/recall failures       # recurring failure patterns and approved learnings
/recall learn          # review pending learnings from repeated failures
/recall <term>         # search indexed messages, commands, failures, and skills
/recall last           # inspect commands and failures from the previous session
```

Command history is captured by the session indexers instead of a separate `/history` command. Use `/recall last`, `/recall <term>`, and `/recall failures` to get back to commands that worked.

---

## Learning System

recall automatically proposes learnings when it spots patterns:
- A command fails 3+ times with the same error type
- A failed command is followed by a successful variant (resolution pair)

```
user@mac ~/myapp > /recall learn

  ## Pending Learnings
  **Approved** (1): **Personal:** 1
  **Pending:** 2

  ### [0] [P:git] SSH authentication failure
    HTTPS tokens expire regularly
    **Fix:** Use SSH remotes — HTTPS tokens expire, SSH keys don't.
    _Source: auto_

  ### [1] [P:python] PYTHONPATH not set
    ModuleNotFoundError resolved by env export
    **Fix:** export PYTHONPATH="$PWD/src"
    _Source: auto_

  ---
  **Actions:**
    `/recall learn --batch` - Accept all pending learnings
    `/recall learn --approve 0` - Approve learning #0
    `/recall learn --reject 0` - Reject learning #0
```

Learnings are organized into **buckets** (ownership contexts):

```json
{
  "bucket": "personal",
  "category": "git",
  "title": "SSH vs HTTPS remotes",
  "description": "HTTPS tokens expire; SSH keys are persistent",
  "solution": "git remote set-url origin git@github.com:org/repo.git"
}
```

---

## Hook Configuration

Claude Code installs register the hooks from `hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session-start",
        "timeout": 5
      }]
    }],
    "SessionEnd": [{
      "hooks": [{
        "type": "command",
        "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session-end",
        "timeout": 30
      }]
    }],
    "PostToolUse": [{
      "matcher": "Bash",
      "hooks": [{
        "type": "command",
        "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/bash-failure",
        "timeout": 10
      }]
    }]
  }
}
```

**Overhead:**
- SessionStart: usually <100ms with compiled fast path (loads context from previous sessions)
- SessionEnd: ~30s (indexes the session)
- PostToolUse/Bash: ~10s per command (failure pattern matching)

---

## Index Structure

Sessions are indexed at `~/.claude/projects/{project}/recall-index.json`:

```json
{
  "version": 2,
  "sessions": {
    "session-uuid": {
      "date": "2026-03-20T09:41:00",
      "summary": "Implementing payroll bonus calculation fix",
      "message_count": 34,
      "command_count": 12,
      "failure_count": 2,
      "topics": ["payroll", "rounding", "tests"],
      "failures": [{ "category": "python_error", "cmd": "python3 bonus.py" }]
    }
  },
  "failure_patterns": {
    "git_error": [{ "cmd": "git push", "resolution": "switch to SSH remote" }]
  },
  "learnings": [
    {
      "bucket": "personal", "category": "git", "title": "SSH vs HTTPS",
      "fix": "Use SSH remotes — HTTPS tokens expire, SSH keys don't.",
      "solution": "git remote set-url origin git@github.com:org/repo.git"
    }
  ]
}
```

---

## File Structure

Plugin layout (installed under `${CLAUDE_PLUGIN_ROOT}`):

```
recall/
├── .codex-plugin/
│   └── plugin.json              # Codex plugin manifest
├── .claude-plugin/
│   └── plugin.json              # plugin manifest
├── commands/
│   └── recall.md                # legacy flat command shim/docs
├── skills/
│   └── recall/
│       ├── SKILL.md             # canonical dispatcher skill
│       └── procedures/          # lazy-loaded save/restart/learn procedures
├── hooks/
│   ├── hooks.json               # hook registration
│   └── scripts/
│       ├── session-start        # SessionStart: Rust fast path wrapper
│       ├── session-start.py     # SessionStart: Python fallback
│       ├── session-end          # SessionEnd wrapper
│       ├── session-end.py       # SessionEnd: indexes session
│       ├── bash-failure         # PostToolUse:Bash wrapper
│       └── bash-failure.py      # PostToolUse:Bash: failure patterns
└── bin/
    ├── recall                   # shell wrapper (Rust fast path → Python fallback)
    ├── recall-sessions.py       # session search / list / cleanup / knowledge CLI
    ├── recall-save.py           # session save + LLM A/B comparison
    ├── recall-save-eval.py      # save eval candidate + comparison log helper
    ├── recall-learn.py          # pending learning review/approve/reject
    └── recall-restart.py        # restart prompt CLI
```

Per-project state (under `~/.claude/projects/{project-slug}/`):

```
recall-index.json    # searchable session index
recall-restarts/     # saved restart prompts
*.jsonl              # raw session files
```

---

## Tips

1. **Save proactively** — run `/recall save` when a session is getting long, not just when you hit the limit.
2. **Search before asking** — `/recall <topic>` often surfaces the exact solution from a past session.
3. **Review learnings weekly** — `/recall learn` turns recent failures into permanent SOPs.
4. **Clean up monthly** — `/recall cleanup --all` removes noise and sensitive data.

---

## Requirements

- Python 3.8+
- Any AI coding agent — Claude Code, Codex, Gemini CLI, or similar

---

## License

MIT — ashrocket collective
