# recall vs. Native Memory Tools: A Full Comparison

This compares recall against what Claude Code, Codex CLI, and Gemini CLI each provide natively for memory and session continuity — including their instruction files (CLAUDE.md, AGENTS.md, GEMINI.md).

---

## What Each Platform Provides Natively

### Claude Code

**CLAUDE.md — static instructions you write**
- Three scopes: organization policy, project-level (`./CLAUDE.md`), user-level (`~/.claude/CLAUDE.md`)
- Loaded at session start; supports `@path/to/file` imports and `.claude/rules/` with path-scoped rules
- You write and maintain these; they don't change based on what happened in past sessions

**MEMORY.md — learnings Claude writes automatically**
- Claude decides what to remember during a session and writes it to `~/.claude/projects/<project>/memory/MEMORY.md`
- First 200 lines loaded at session start; detailed topic files load on-demand
- Per-project, machine-local; controlled via `/memory` command or `autoMemoryEnabled` setting

**Session resume**
- `claude -c` continues the most recent session in the current directory
- `claude -r <id|name>` resumes a specific session by ID or name
- Sessions persist on-disk by default; `--name` flag for naming sessions

---

### Codex CLI

**AGENTS.md — static instructions you write**
- Two-level hierarchy: `~/.codex/AGENTS.md` (global) + project root `AGENTS.md`
- Override mechanism: files closer to working directory override earlier guidance
- 32 KiB combined size cap; injected as the first user turn of every session (automatically)
- You write and maintain these; Codex reads them as context, not as a memory system

**Session resume**
- `codex resume` continues a session by ID; `codex resume --last` picks up the most recent
- `codex fork` creates a new thread from a previous session, preserving original transcript
- Sessions stored as JSONL in `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`

**Background memory**
- Post-rollout processing can write workspace-scoped facts asynchronously
- No explicit memory commands; no `/memory` equivalent; limited user control over what's stored

---

### Gemini CLI

**GEMINI.md — static instructions you write**
- Three tiers: `~/.gemini/GEMINI.md` (global), workspace directories, and just-in-time (loaded when Claude reads a file)
- `@file.md` import syntax for modular organization
- Concatenated and displayed via `/memory show`; force-reloaded via `/memory reload`

**save_memory tool — learnings Claude writes**
- The `save_memory` tool appends facts to the `## Gemini Added Memories` section of `~/.gemini/GEMINI.md`
- Cross-session, user-level; accessible across projects
- `/memory add <text>` is the user-facing command
- Gemini decides when to call this during a session

**Session resume**
- `/chat save` / `/chat resume` for branching and resuming conversation history
- Less explicit than Claude Code's session ID system; relies more on memory than transcript replay

---

## Where They All Fall Short (Without recall)

| Gap | Claude Code | Codex | Gemini |
|-----|------------|-------|--------|
| Automatic session indexing | ✗ | ✗ | ✗ |
| Searchable history (`/recall auth`) | ✗ | ✗ | ✗ |
| Command + failure tracking | ✗ | ✗ | ✗ |
| Error pattern categorization | ✗ | ✗ | ✗ |
| Cross-platform unified index | ✗ | ✗ | ✗ |
| Proposed learnings from failures | ✗ (manual) | ✗ | ✗ (limited) |
| Session context auto-injected at start | ✗ | ✗ | ✗ |

All three platforms provide ways to inject static instructions (the `*.md` files) and some form of note-taking for Claude to write into. None of them automatically capture session history, search it, or surface relevant context at the start of the next session.

---

## What recall Adds

**Automatic session indexing**
Every session is indexed at end: user messages (summarized), every bash command, every failure with exit code + error categorization (`not_found`, `permission_denied`, `python_error`, etc.).

**SessionStart context injection**
At the start of each new session, relevant context from prior sessions is automatically injected — last session summary, recurring failure patterns, pending tasks. No prompting required.

**Search**
- `/recall <term>` — full-text search across session history
- `/recall '.p8'` and `/recall /.*\.p8/` — literal and regex search for precise artifacts
- `/recall failures` — grouped error patterns with counts and last occurrences
- `/recall last` — full detail of the previous session

**Learning proposals from failures**
When the same error class recurs 3+ times, recall proposes a learning. You review and approve via `/recall learn`. Approved learnings are injected in future SessionStart context.

**Cross-platform unified index**
Claude Code, Codex, and Gemini CLI sessions all land in the same JSON index at `~/.claude/projects/<project>/recall-index.json`. A Codex session from Tuesday shows up in `/recall last` on Wednesday in Claude Code.

---

## How They Fit Together

These are complementary layers, not alternatives:

```
┌─────────────────────────────────────────────────────┐
│  CLAUDE.md / AGENTS.md / GEMINI.md                  │
│  Static rules and project context YOU write.         │
│  "Always use kare-dev-admin AWS profile."            │
│  "Never commit to master directly."                  │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│  MEMORY.md / save_memory (native auto-memory)        │
│  Domain knowledge and decisions Claude writes.       │
│  "The AR sprint owner is Christel."                  │
│  "Sample uses Funding == 'ECBH' filter."           │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│  recall                                        │
│  Session mechanics Claude captures automatically.   │
│  "Tuesday's session: fixed the auth middleware."     │
│  "This command fails 3x a week — here's the fix."   │
│  "You were in the middle of the JWT refactor."       │
└─────────────────────────────────────────────────────┘
```

**Use the instruction files** for rules and conventions that should always apply.

**Use native auto-memory** for strategic context, domain knowledge, and facts you want Claude to retain long-term across projects.

**Use recall** for session mechanics: what happened, what failed, what was half-done, and patterns across dozens of sessions over months.

---

## Overhead Comparison

| Layer | Startup cost | Per-command cost | Shutdown cost |
|-------|-------------|-----------------|---------------|
| CLAUDE.md / AGENTS.md / GEMINI.md | ~0ms (preloaded) | 0 | 0 |
| Native auto-memory | ~0ms (loaded with context) | 0 | ~1–5s (async write) |
| recall (full) | ~5s (SessionStart hook) | ~10s (PostToolUse, failures only) | ~30s (SessionEnd index) |
| recall (minimal history only) | ~2s | 0 | ~10s |

The `--minimal` install skips PostToolUse hooks and disables per-command failure tracking, cutting overhead significantly.

---

## Verdict

| Use case | Best tool |
|----------|-----------|
| Project rules and conventions | CLAUDE.md / AGENTS.md / GEMINI.md |
| Domain knowledge, strategic context | Native auto-memory (MEMORY.md / save_memory) |
| Session history and search | recall |
| Recurring failure patterns | recall |
| Multi-platform unified history | recall (only option) |
| Zero overhead, zero maintenance | Native instruction files only |
| Resume specific past session | `claude -r` / `codex resume` (native) |

The ideal setup: instruction files for rules, native auto-memory for strategy, recall for mechanics. They don't overlap — they stack.
