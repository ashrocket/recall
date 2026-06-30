# Git-Backed Sync & Architecture Decision Memos

## Summary

Two new capabilities spanning two plugins:

1. **Git-backed sync** (recall feature) — Store recall data (restart prompts, learnings, SOPs, session metadata) in a private git repo on GitHub, GitLab, or Bitbucket. Git is used as a dumb transport layer; the data format is designed so merge conflicts cannot occur by construction. Raw session transcripts never sync by default. When agent-adm is also installed, sync transparently includes ADM files.

2. **Architecture Decision Memos** (new plugin: **agent-adm**) — A standalone skill that tracks architectural decisions with arguments for/against, a revisit date, and success criteria. Both Claude and the user can create them. Stale ADMs surface at session start for review. Works independently of recall, but recall's sync feature can transport ADM data when both are installed.

### Plugin relationship

```
agent-adm (standalone)          recall (standalone)
├── /adm command                ├── /recall command
├── ADM creation & review       ├── session memory & search
├── ADM file format & storage   ├── restart prompts
└── revisit notifications       ├── learnings & SOPs
                                ├── git sync engine
                                └── detects agent-adm → syncs ADM files
```

- **agent-adm alone**: ADMs work fully — create, review, snooze, retire. Stored locally.
- **recall alone**: session memory, restarts, learnings, sync. No ADM features.
- **Both installed**: recall's sync engine discovers ADM files and includes them in push/pull. ADM revisit notifications appear alongside recall's session start context.

## Research basis

Design validated through synthetic user research with 9 personas across 3 platforms (Claude Code, Codex, Gemini CLI) and 3 coding styles (conservative, moderate, aggressive). All recommendations achieved majority or unanimous support across the panel. Full interview transcripts available in conversation history.

## Goals

1. Recall data survives across machines without manual copying
2. Architectural decisions are captured, tracked, and revisited on schedule
3. ADMs work independently — no recall dependency required
4. Zero merge conflicts by design — git is transport, not workflow
5. Privacy-safe defaults — no secrets leave the machine
6. Works with GitHub, GitLab, and Bitbucket private repos
7. Setup is one command for the common case

## Non-goals

- Team/shared sync (multi-user repos) — strictly personal for v1
- Syncing raw session transcripts by default
- Encryption at rest (v2 consideration for enterprise users)
- Real-time / continuous sync daemon (v2)
- Contextual ADM surfacing based on file edits (v2)
- Requiring both plugins for either to function

---

## Feature 1: Git-Backed Sync

### Data architecture

The sync repo uses a flat, conflict-free file layout. Every artifact is its own file. The index is regenerable from individual files — it is never synced directly.

```
recall-data/                          # the private git repo
├── .recallignore                     # user-defined sync exclusions
├── restarts/
│   ├── 2026-03-20_payroll-fix.yaml
│   └── 2026-03-28_auth-refactor.yaml
├── learnings/
│   ├── 2026-03-15_git-ssh-vs-https.yaml
│   └── 2026-03-22_python-path.yaml
├── adm/
│   ├── 2026-03-10_postgres-over-dynamodb.yaml
│   └── 2026-03-14_rs256-jwt-signing.yaml
├── sops/
│   ├── git_error.yaml
│   └── permission_denied.yaml
└── sessions/
    ├── 2026-03-20_abc123.yaml        # metadata only, not transcript
    └── 2026-03-28_def456.yaml
```

Key properties:
- **One file per artifact.** Two machines creating different sessions produce different files. No file is ever modified by two machines.
- **Filenames include date + slug/ID.** Globally unique, human-readable, sortable.
- **Index is local-only and regenerable.** `recall-index.json` is rebuilt from the individual files on pull. It is listed in `.gitignore`.
- **Session metadata files contain summaries only.** No raw commands, no bash output, no file paths. Fields: session ID, date, project name, topic tags, message count, command count, failure count, source platform, source machine hostname.
- **YAML format** for all synced files. Human-readable, supports comments, inspectable with `cat`.

### What gets synced

| Data type | Synced by default | Opt-in | Notes |
|-----------|-------------------|--------|-------|
| ADMs | Yes | — | Highest-value artifact |
| Restart prompts | Yes | — | Killer sync use case |
| Learnings (approved) | Yes | — | Curated, no secrets |
| SOPs | Yes | — | Generic failure playbooks |
| Session metadata | Yes (stripped) | Full metadata | Summaries only, no commands/paths |
| Raw transcripts | **No** | `sync.include_transcripts = true` | Large, may contain secrets, explicit opt-in with warning |

Each category is independently toggleable:

```yaml
sync:
  include:
    adm: true
    restarts: true
    learnings: true
    sops: true
    session_metadata: true
    transcripts: false        # opt-in, warned on enable
```

### Sync timing

Default: **auto-pull on session start, auto-push on session end.**

```yaml
sync:
  mode: auto                  # auto | auto-pull | manual
```

| Mode | Pull behavior | Push behavior |
|------|--------------|---------------|
| `auto` | On session start | On session end |
| `auto-pull` | On session start | Only on `/recall sync push` |
| `manual` | Only on `/recall sync pull` | Only on `/recall sync push` |

Behavior on failure:
- **Pull failure** (network, auth): skip silently, log warning, show one-line notice at session start. Never block session start.
- **Push failure** (network, auth): queue locally, retry on next session end. Show one-line notice at next session start: `recall: 3 items pending sync (last push failed — retrying)`.
- **Push timeout**: 10 seconds max. If exceeded, queue and move on.

### Setup flow

Three paths, all leading to the same config:

**Quick path** (README default):
```bash
/recall sync init --github     # or --gitlab, --bitbucket
```
Creates a private repo, configures auth from existing CLI tools (`gh`, `glab`, SSH keys), pushes initial data. One command.

**Guided path** (interactive):
```bash
/recall sync init
```
Prompts for: provider → repo URL → auth method → test push. Step by step.

**Config path** (automation / ephemeral VMs):
```bash
export RECALL_SYNC_REPO=git@github.com:user/recall-data.git
```
Or in config file:
```yaml
# ~/.config/recall/sync.yaml
sync:
  repo: git@github.com:user/recall-data.git
  mode: auto
```
On first session start, auto-initializes from config. No interactive prompts.

### Auth strategy

The plugin uses the user's existing git auth. It does not implement its own OAuth flow or token management.

- **SSH URLs** (`git@...`): uses existing SSH keys
- **HTTPS URLs** (`https://...`): uses existing credential helpers (`gh auth`, `glab`, git credential store)
- **Deploy tokens**: user pastes token during guided setup, stored in system keychain or config file

The plugin never stores credentials in its own files. It delegates to git's credential system.

### Provider support

| Provider | SSH | HTTPS | Auto-create repo | CLI tool used |
|----------|-----|-------|-------------------|--------------|
| GitHub | Yes | Yes | Yes | `gh` |
| GitLab | Yes | Yes | Yes | `glab` or API |
| Bitbucket | Yes | Yes | Yes | Bitbucket API |

If the CLI tool isn't available, the user provides a repo URL and creates the repo manually. The guided setup detects which tools are available.

### Private repo enforcement

On `sync init`, the plugin checks whether the target repo is public. If public:

```
⚠ Warning: this repo is PUBLIC. Recall data may contain sensitive information.
  Recommended: use a private repo.
  Continue anyway? [y/N]
```

Default is N. The user must explicitly opt in to a public repo.

### Secret scanning

Before every push, the plugin scans all staged files for common secret patterns:

- AWS keys (`AKIA...`)
- API tokens (`sk-...`, `ghp_...`, `glpat-...`)
- Bearer tokens (`Bearer ...`)
- Connection strings (`postgres://...`, `mongodb://...`)
- Generic password patterns (`password=`, `secret=`)
- High-entropy strings that look like tokens

Behavior: **warn and block with one-keystroke override.**

```
⚠ Possible API key detected in learnings/2026-03-28_stripe-setup.yaml
  Line 4: sk-test-...

  [r]edact and push  [s]kip this file  [p]ush anyway  [a]bort
```

The sanitizer from the existing share/import feature is reused here. Same patterns, same engine.

Config override for strict/permissive modes:

```yaml
sync:
  secret_scan: warn           # warn | strict | off
```

- `warn` (default): scan, show findings, let user decide per-file
- `strict`: block push entirely if secrets detected, no override
- `off`: no scanning (use at your own risk)

### `.recallignore`

Users can exclude specific projects or patterns from sync:

```
# Never sync sessions from infrastructure repos
projects/demo-infra-*
projects/secrets-*

# Exclude specific ADMs
adm/2026-03-15_internal-auth-*.yaml
```

File lives in the sync repo root. Patterns follow gitignore syntax.

### CLI commands

```bash
/recall sync                  # status: show sync state
/recall sync init             # guided setup
/recall sync init --github    # quick setup (also --gitlab, --bitbucket)
/recall sync push             # manual push
/recall sync push --dry-run   # show what would be pushed
/recall sync pull             # manual pull
/recall sync --verify         # confirm all local data is pushed (pre-destroy)
/recall sync config           # show current sync config
/recall sync pause            # pause auto-sync until resumed
/recall sync resume           # resume auto-sync
```

### Terminal output

Three verbosity levels. Default is **normal**.

```bash
# --quiet (or auto-detected in non-interactive contexts)
✓ Synced (3↓ 2↑)

# normal (default)
↓ Pulled 2 items from laptop (2026-03-28)
↑ Pushed 3 items to remote
✓ Synced — 47 sessions, 12 restarts across 2 machines

# --verbose
Pulling from origin/main...
  ↓ 2 restart prompts (laptop, 2026-03-28)
  ↓ 1 ADM (laptop, 2026-03-29)
Pushing local changes...
  Pre-push scan: 4 files clean, 0 secrets detected
  ↑ 1 restart prompt (auth-flow-refactor)
  ↑ 3 learnings (git, python, aws)
Synced. 3 files pulled, 4 files pushed.
Last sync: 2026-03-30 09:14 UTC
```

### First-time experience

After the user has **3 indexed sessions** and has not configured sync, show one line at the bottom of `/recall` output:

```
Tip: sync your recall data across machines with /recall sync init
```

Show this tip at most 3 times. Never block, never modal, never repeat after dismissal.

### Conflict resolution

By design, conflicts cannot occur during normal operation:
- Different machines create different files (unique session IDs, timestamps)
- The index is local-only and regenerated from files
- ADMs are created once and modified only on one machine at a time

If a conflict does occur (manual git editing, race condition):
- Attempt fast-forward merge
- If fast-forward fails, keep both versions with machine-name suffix
- Regenerate index from all files
- Log what happened, never silently discard data

### Config file location

```
~/.config/recall/sync.yaml
```

XDG-compliant. Global, not per-project. One config for all repos.

---

## Feature 2: Architecture Decision Memos (agent-adm plugin)

agent-adm is a **standalone plugin** — a sibling to recall, not a child of it. It has its own `plugin.json`, its own commands, its own hooks. It can be installed and used without recall.

When both plugins are installed, recall's sync engine discovers agent-adm's data directory and includes ADM files in push/pull operations. This is the only integration point — recall syncs ADM files, agent-adm owns everything else.

### What is an ADM

An ADM captures:
- **The decision** that was made
- **Arguments for** the chosen approach
- **Arguments against** (trade-offs accepted)
- **Revisit date** — when to re-evaluate
- **Success criteria** — how to judge if the decision was correct
- **Status** — active, review, retired, superseded

ADMs are different from learnings. Learnings capture "what worked" patterns. ADMs capture "why we chose this over that" with an explicit mechanism to revisit the choice.

### File format

```yaml
# adm/2026-03-30_postgres-over-dynamodb.yaml
id: "adm-007"
decision: "Use PostgreSQL over DynamoDB for payment records"
status: active                    # active | review | retired | superseded

created: 2026-03-10
created_by: claude                # claude | user
source_platform: claude-code      # claude-code | codex | gemini-cli
source_machine: ashbook-pro
project: myapp

arguments_for:
  - "ACID compliance required for financial data"
  - "Team has deep PostgreSQL expertise"
  - "Existing monitoring and backup tooling"

arguments_against:
  - "DynamoDB auto-scaling is simpler"
  - "Lower ops burden with managed service"
  - "AWS-native integration for Lambda triggers"

revisit:
  date: 2026-04-10
  criteria: "P99 query latency <50ms at 1M records after load testing"
  snoozed_until: null             # set by snooze command

supersedes: null                  # ID of ADM this replaces
superseded_by: null               # ID of ADM that replaced this

history:                          # append-only review log
  - date: 2026-03-10
    action: created
    note: "Initial decision during payment service setup"
```

### Creation modes

Configurable via:
```yaml
adm:
  creation: suggest               # suggest | approve | queue | silent
```

| Mode | Behavior |
|------|----------|
| `suggest` (default) | Claude proposes inline with one-keystroke accept/skip |
| `approve` | Claude proposes inline, user must explicitly approve and can edit |
| `queue` | Claude queues proposals, presents at session end for batch review |
| `silent` | Claude auto-creates, user reviews later via `/adm` |

**`suggest` mode (default) — inline proposal:**

```
┌ adm: decision proposal ─────────────────────────────────┐
│ Use PostgreSQL over DynamoDB for payment records      │
│                                                       │
│ For:  ACID compliance, team expertise, existing infra │
│ Against: DynamoDB scaling, lower ops burden            │
│ Revisit: 2026-04-10 (after load testing)              │
│                                                       │
│ [y] Save  [e] Edit  [n] Skip                         │
└───────────────────────────────────────────────────────┘
```

**`silent` mode — one-line notification:**

```
[adm: +1 "PostgreSQL over DynamoDB"]
```

### When Claude should propose an ADM

Claude proposes an ADM when making a decision that meets ANY of these criteria:
- Introduces a new infrastructure dependency (database, cache, queue, cloud service)
- Chooses between competing technologies or frameworks
- Affects multiple services or modules
- Would take more than a day to reverse
- Changes data storage format or schema strategy
- Picks an authentication/authorization approach

Claude should NOT propose an ADM for:
- Code style choices (tabs vs spaces, naming conventions)
- Library version selections
- Routine implementation patterns
- Anything easily reversed in under an hour

### Revisit mechanism

**Session start notification:**

At session start, if any ADMs have `revisit.date <= today` and `snoozed_until` is null or past:

```
adm: 2 decisions due for review — /adm review
```

One line. Non-blocking. Shown alongside the existing session context summary.

**Snooze:**

```bash
/adm snooze 3 7d                 # snooze ADM #3 for 7 days
/adm snooze --all 14d            # snooze all due ADMs for 14 days
```

Snoozed ADMs don't appear in session start notifications until the snooze expires.

**Review flow:**

```bash
/adm review                      # review all due ADMs interactively
```

```
ADM #2: RS256 for JWT signing (created 2026-03-14, due 2026-03-28)

  For:   Multi-service verification without shared secret
  Against: Larger tokens, key rotation complexity
  Criteria: "Confirm after load testing — token verification <5ms at P99"

  Load testing is complete. What's the verdict?

  [k] Keep (still the right call)
  [r] Revise (update arguments or criteria)
  [s] Supersede (replace with a new ADM)
  [t] Retire (decision no longer relevant)
  [z] Snooze (remind me later)
```

On **keep**: appends to history log, optionally sets a new revisit date.
On **revise**: opens the ADM for editing, appends revision to history.
On **supersede**: creates a new ADM, links old → new via `superseded_by`.
On **retire**: sets status to `retired`, appends to history.

### CLI commands

agent-adm owns the `/adm` command (not `/recall adm` — it's a peer, not a subcommand):

```bash
/adm                              # list all ADMs for current project
/adm --all                        # list ADMs across all projects
/adm create                       # interactive creation
/adm create "decision" \
  --for "..." --against "..." \
  --revisit 2026-06-01 \
  --criteria "..."                # one-liner creation (flags)
/adm show 3                       # show full details of ADM #3
/adm review                       # review all due ADMs
/adm review 3                     # review specific ADM
/adm snooze 3 7d                  # snooze ADM #3 for 7 days
/adm retire 3                     # retire ADM #3
/adm search "postgres"            # search ADMs by keyword
/adm --format=json                # machine-readable output (all commands)
```

### Terminal output for `/adm`

```
Architecture Decision Memos — myapp

  #  Decision                              Status    Revisit
  1  PostgreSQL over DynamoDB              active    Apr 10
  2  RS256 for JWT signing                 OVERDUE   Mar 28
  3  Redis for session cache               active    —
  4  Monorepo over polyrepo                retired   —

3 active, 1 overdue — /adm review
```

### ADM local storage

agent-adm stores its data at `~/.claude/adm/` (global, not per-project):

```
~/.claude/adm/
├── adm-index.json                # local index, regenerable
├── config.yaml                   # agent-adm config (creation mode, etc.)
└── projects/
    └── myapp/
        ├── 2026-03-10_postgres-over-dynamodb.yaml
        └── 2026-03-14_rs256-jwt-signing.yaml
```

The index is regenerable from the individual YAML files.

### agent-adm hooks

agent-adm registers its own hooks independently:

- **SessionStart**: check for overdue ADMs, show one-line notification
- **Stop** (optional): if creation mode is `queue`, present pending ADM proposals before session ends

These hooks work whether or not recall is installed.

### agent-adm plugin.json

```json
{
  "name": "agent-adm",
  "version": "1.0.0",
  "description": "Architecture Decision Memos — track, revisit, and evolve architectural choices.",
  "author": { "name": "ashrocket collective" },
  "repository": "https://github.com/ashrocket/agent-adm",
  "license": "MIT"
}
```

---

## Integration: recall + agent-adm

When both plugins are installed, recall's sync engine discovers agent-adm's data directory and includes ADM files in push/pull. This is a **one-way dependency**: recall knows about agent-adm, not the other way around.

### Discovery mechanism

On sync push/pull, recall checks if `~/.claude/adm/` exists. If it does:
- ADM YAML files are included in the sync repo under `adm/`
- The `sync.include.adm` config toggle controls this (default: true)
- agent-adm's index is NOT synced — it's regenerated locally after pull

If `~/.claude/adm/` does not exist, recall ignores ADMs entirely. No errors, no warnings.

### Session start hook coordination

If both plugins are installed, both register SessionStart hooks:
- recall's hook: loads session context, runs sync pull
- agent-adm's hook: checks for overdue ADMs

They run independently. agent-adm's revisit notification appears alongside recall's session context. No coordination required — both output to the same hook stream.

### Sync integration details

```
recall sync push:
  1. Gather recall files (restarts, learnings, sops, session metadata)
  2. Check if ~/.claude/adm/ exists → if yes, gather ADM files
  3. Run secret scan on all gathered files
  4. Git add, commit, push

recall sync pull:
  1. Git pull
  2. Distribute recall files to recall directories
  3. If ~/.claude/adm/ exists → distribute ADM files to adm directory
  4. Regenerate recall index
  5. If agent-adm installed → trigger agent-adm index regeneration
```

---

## Integration with existing recall features

### Session start hook

The existing `session-start.py` hook gains one new responsibility:

1. **Sync pull** (if sync configured and mode is `auto` or `auto-pull`)

This is a fast operation — pull is a `git pull --ff-only`. Target: <2 seconds additional overhead.

### Session end hook

The existing `session-end.py` hook gains:

1. **Sync push** (if sync configured and mode is `auto`)

### `/recall save` (restart prompts)

Restart prompts are now YAML files in the sync repo. When the user runs `/recall save`, the restart prompt is written to both the local recall directory and the sync repo's `restarts/` directory. Pushed on next sync.

### `/recall` (session list)

Session list now shows source machine for synced sessions:

```
Recent sessions — myapp (51 total, 2 machines)

  today       payroll-bonus-fix     12 msgs  3 cmds   ashbook-pro
  2026-03-19  auth-flow-refactor    34 msgs  18 cmds  linux-desktop
  2026-03-18  api-rate-limiting     28 msgs  22 cmds  ashbook-pro
```

---

## Config file schemas

**recall sync config** (`~/.config/recall/sync.yaml`):

```yaml
sync:
  repo: git@github.com:user/recall-data.git
  mode: auto                      # auto | auto-pull | manual
  secret_scan: warn               # warn | strict | off
  include:
    adm: true                     # sync ADM files if agent-adm is installed
    restarts: true
    learnings: true
    sops: true
    session_metadata: true
    transcripts: false
```

**agent-adm config** (`~/.claude/adm/config.yaml`):

```yaml
adm:
  creation: suggest               # suggest | approve | queue | silent
  revisit_notify: true            # show session-start notification
  snooze_default: 7d              # default snooze duration
```

Each plugin owns its own config. No cross-references.

---

## Pre-destroy verification

For ephemeral VM users, a verification command confirms all local data has been pushed:

```bash
/recall sync --verify
```

```
✓ All local data pushed. 0 unsynced items. Safe to terminate.
```

Or if unsynced:

```
✗ 2 items NOT synced (push failed — check network)
  - learning: ray-cluster-autoscaling.yaml
  - adm: gpu-memory-optimization.yaml
DO NOT destroy this VM until sync completes.
```

---

## File structure changes

**recall** (new/modified files):

```
recall/
├── lib/
│   ├── sync.py                   # git sync engine (push, pull, init)
│   ├── sync_auth.py              # provider auth detection (gh, glab, ssh)
│   └── sync_scan.py              # secret scanning before push
├── hooks/scripts/
│   ├── session-start.py          # modified: add sync pull
│   └── session-end.py            # modified: add sync push
└── commands/
    └── recall.md                 # modified: add sync subcommands
```

**agent-adm** (new plugin, separate repo):

```
agent-adm/
├── .claude-plugin/
│   └── plugin.json
├── lib/
│   ├── adm.py                   # ADM CRUD, review, snooze, search
│   └── adm_index.py             # index generation and queries
├── bin/
│   └── adm-cli.py               # /adm CLI entrypoint
├── hooks/
│   ├── hooks.json                # SessionStart hook for revisit check
│   └── scripts/
│       └── adm-session-start.py  # check for overdue ADMs
├── commands/
│   └── adm.md                   # /adm skill definition
├── skills/
│   └── adm/
│       └── SKILL.md
├── templates/
│   └── adm.yaml                 # ADM template for creation
├── README.md
└── AGENTS.md
```

---

## Testing strategy

**recall (sync):**
- **Unit tests** for `lib/sync.py`: init, push, pull, conflict resolution, index regeneration
- **Unit tests** for `lib/sync_scan.py`: secret detection patterns, false positive rate
- **Integration test**: two local git repos simulating two machines, push/pull cycle, verify no conflicts
- **Integration test**: sync with agent-adm installed — verify ADM files are discovered and synced
- **Integration test**: sync without agent-adm — verify no errors, no ADM references

**agent-adm:**
- **Unit tests** for `lib/adm.py`: CRUD, revisit checks, snooze, supersede, history append
- **Unit tests** for `lib/adm_index.py`: index generation, queries, regeneration from files
- **Integration test**: ADM lifecycle — create, review, snooze, revisit, supersede, retire
- **Integration test**: SessionStart hook — overdue ADM detection and notification

---

## Migration path

Existing recall users have data in `~/.claude/projects/{project}/`:
- `recall-index.json`
- `restarts/`
- `*.jsonl` (raw sessions)

On first `sync init`, the plugin:
1. Converts existing restart prompts to YAML format in the sync repo
2. Converts existing learnings to YAML files
3. Creates session metadata YAML files from index entries (not transcripts)
4. Does NOT touch the existing local files — they remain as the local source of truth
5. The sync repo is additive — it gets copies, not moves

---

## Scope for v1 vs v2

### v1 (this spec)

**recall:**
- Git sync with GitHub, GitLab, Bitbucket
- Secret scanning before push
- `--verify` / `--pre-destroy` command
- `--dry-run` on push
- `.recallignore` support
- Discovery and sync of agent-adm files when installed

**agent-adm:**
- ADM creation (all 4 modes: suggest, approve, queue, silent)
- Review, snooze, retire, supersede workflows
- Session start notifications for overdue ADMs
- `--format=json` on all commands
- Standalone operation without recall

### v2 (future)
- Encryption at rest (`age` or `git-crypt`) — recall sync feature
- Contextual ADM surfacing when editing related files — agent-adm
- Continuous sync daemon mode — recall
- Cross-tool source tracking in ADM metadata (already in schema, UI deferred) — agent-adm
- Weekly ADM digest (email/webhook) — agent-adm
- Transcript sync with aggressive sanitization — recall
- Team/shared sync repos — recall
