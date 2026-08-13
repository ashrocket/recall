# recall vs. Native Memory Tools: A Full Comparison

This compares recall against what Claude Code and Codex CLI each provide natively for memory and session continuity — including their instruction files (CLAUDE.md, AGENTS.md).

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

## Where They Fall Short (Without recall)

| Gap | Claude Code | Codex |
|-----|------------|-------|
| Automatic session indexing | ✗ | ✗ |
| Searchable history (`/recall auth`) | ✗ | ✗ |
| Command + failure tracking | ✗ | ✗ |
| Error pattern categorization | ✗ | ✗ |
| Cross-platform unified index | ✗ | ✗ |
| Proposed learnings from failures | ✗ (manual) | ✗ |
| Session context auto-injected at start | ✗ | ✗ |

Both platforms provide ways to inject static instructions (the `*.md` files) and some form of note-taking for Claude to write into. None of them automatically capture session history, search it, or surface relevant context at the start of the next session.

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
Claude Code and Codex sessions land in the same JSON index at `~/.claude/projects/<project>/recall-index.json`. A Codex session from Tuesday shows up in `/recall last` on Wednesday in Claude Code.

---

## How They Fit Together

These are complementary layers, not alternatives:

```
┌─────────────────────────────────────────────────────┐
│  CLAUDE.md / AGENTS.md                              │
│  Static rules and project context YOU write.         │
│  "Always use kare-dev-admin AWS profile."            │
│  "Never commit to master directly."                  │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│  MEMORY.md (Claude Code native auto-memory)          │
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
        │
        │  /recall memory sync  — approved learnings and SOPs
        ▼        are promoted up into the native layer
```

**Use the instruction files** for rules and conventions that should always apply.

**Use native auto-memory** for strategic context, domain knowledge, and facts you want Claude to retain long-term.

**Use recall** for session mechanics: what happened, what failed, what was half-done, and patterns across dozens of sessions over months.

The layers no longer just sit next to each other. recall's distilled output — the learnings you approve and the SOPs you write — is promoted *into* the native auto-memory layer, so it loads at the start of every session instead of waiting for you to run a `/recall` subcommand. See "The native memory bridge" below.

---

## The native memory bridge

`/recall memory sync` writes recall's distilled knowledge into Claude Code's
per-project auto-memory directory, `~/.claude/projects/<slug>/memory/`. Claude
Code injects that directory's `MEMORY.md` index into every session in the
project — as a `<system-reminder>` on the first user message — and reads the
topic files it points at on demand, so promoted knowledge arrives without anyone
running a command.

```
/recall memory              # what is promoted, and what was held back
/recall memory sync         # promote approved learnings and SOPs
/recall memory sync -n      # dry run (same gate as the real thing)
/recall memory enable       # also promote automatically on approval
/recall memory disable      # stop promoting automatically
/recall memory clear        # remove everything recall promoted
/recall memory sync --codex # write the recall block in AGENTS.md instead
```

**The pinned playbook.** Index pointers only help if the model chooses to follow
them. Claude Code also injects the *full body* of up to four "pinned" memories
into every session, so recall folds everything it promotes into one pinned file,
`recall-project-playbook.md` — the rules are present rather than merely
available. recall claims exactly one of those four slots and never evicts yours:
if you already have four pinned memories, it declines to pin and says so. The
playbook renders deterministically, so an unchanged sync does not rewrite it —
which matters, because pinned memories are ranked by modification time and a
file that rewrote itself on every sync would float above your own pins.

**Codex.** Codex has no memory directory, so ownership there is a *region*
rather than a file: a marker-fenced block in the project's `AGENTS.md`, written
by `--codex`. Everything outside the fence is preserved byte for byte, and
recall will not create an `AGENTS.md` that does not already exist. Both targets
share the same documents and the same promotion gate; only the write strategy
differs.

**Hand-edits win.** Every promoted file records a hash of what recall wrote. Edit
one and recall detects it, then refuses to overwrite *or* prune it — your version
stands. Files also record which recall installation wrote them, so prune never
deletes a file another writer owns.

**Promotion is opt-in and never a side effect.** `sync` is an explicit
instruction, so it runs when you ask. Promoting automatically when you approve a
learning is off until you run `/recall memory enable` — writing into Claude
Code's own config directory is not something to switch on as a by-product of
another command. And recall will not *create* the memory directory as a side
effect: if it does not exist yet, only an explicit `sync` brings it into being.

**Caveat on the surface itself.** Auto-memory injection is subject to
server-side feature gating, a model-dependent check, the `autoMemoryEnabled`
setting, and the `CLAUDE_CODE_SIMPLE` / `CLAUDE_CODE_REMOTE` modes. It can be
turned off without a release, and recall cannot detect that from outside. The
failure mode is quiet rather than damaging: promoted files stay on disk and stop
being read.

**What gets promoted.** `MEMORY.md` loads into *every* session, so the budget is
scarce and the filter is deliberately strict. Approved learnings carrying real,
transferable guidance become `feedback` memories; SOPs become `reference`
memories. Held back are recall's machine-extracted incident records — failure
streak counts (`Recurring general errors (3x in session)`) and one-off command
substitutions (`Use instead: \`<literal command>\``). Those remain available in
`/recall failures`, where they belong. `/recall memory sync` prints what it held
back and why, so a filtered learning is never a silently lost one.

**What recall will not touch.** Every promoted file is named `recall-*.md` and
carries `metadata.source: recall` in its frontmatter. recall only ever rewrites
or prunes files matching *both* markers, and in `MEMORY.md` it only rewrites
pointer lines that link a `recall-*.md` target. Memories you or Claude wrote are
preserved verbatim, including their position in the index. Content is run
through recall's secret scanner before it is written.

**Platform scope.** Claude Code only — Codex has no per-project auto-memory
directory. Set `RECALL_NATIVE_MEMORY=0` to disable the
bridge entirely; it also stays off when you have disabled auto-memory through
`CLAUDE_CODE_DISABLE_AUTO_MEMORY`.

### Why not the memory stores API?

Claude Code 2.1.227+ also ships an org **memory stores** REST API
(`/v1/memory_stores/...`), plus a `CLAUDE_MEMORY_STORES` environment variable
that declares named stores and a `promptIndex` file for each. It looks like the
natural integration point. Measured against the shipped 2.1.229 binary, it is
not reachable from a local CLI session today:

- **Declaring a store costs you the index.** Verified by capturing the HTTP
  request Claude Code actually sends, with a canary token seeded in `MEMORY.md`
  and an isolated config directory. With the variable unset, empty, or
  whitespace, the canary is in the request. With *any* non-empty value —
  including a garbage value that declares no store at all — it is gone, and the
  memory paragraph is replaced by "There is no separate private memory directory
  in this session." The check is only whether the variable is set.
- **The replacement did not fire.** A store canary with `promptIndex` set never
  reached the request, and the declared mount materialised as an empty
  directory — it does not mirror the `path` you give it. This was measured under
  API-key auth in an isolated config; managed and org sessions plausibly do
  qualify, so read this as "does not work locally", not "cannot work".
- **You cannot point it at your own server.** `CLAUDE_CODE_MEMORY_API_BASE_URL`
  is never read in 2.1.229 — every occurrence is a string literal inside an
  env-var allowlist, with no read site anywhere in the bundle. Store `path`
  values are API routes (`/v1/code/memory/...`), not filesystem paths.

So recall never sets `CLAUDE_MEMORY_STORES`. `/recall memory store-env` prints
the declaration, with these caveats, for when org memory stores become reachable
from local sessions. The promoted files are already shaped like memory-store
documents, so that transition is a change of transport, not of content.

**Reproducing this yourself**, on any Claude Code version — the findings above
are pinned to 2.1.229 and the internals will move, but the check does not:

```bash
export CLAUDE_CONFIG_DIR=$(mktemp -d)          # never touch your real memory
mkdir -p "$CLAUDE_CONFIG_DIR/projects/$(pwd | tr / -)/memory"
echo 'The canary token is CANARY-1234.' \
  > "$CLAUDE_CONFIG_DIR/projects/$(pwd | tr / -)/memory/MEMORY.md"

claude -p 'Reply with any canary token in your context, else NONE.'
CLAUDE_MEMORY_STORES='x' \
  claude -p 'Reply with any canary token in your context, else NONE.'
```

If the first prints the token and the second prints `NONE`, the behaviour still
holds. That two-line check is worth more than any note about internals.

---

## Overhead Comparison

| Layer | Startup cost | Per-command cost |
|-------|-------------|-----------------|---------------|
| CLAUDE.md / AGENTS.md | ~0ms (preloaded) | 0 |
| Native auto-memory | ~0ms (loaded with context) | 0 |
| recall (full) | ~5s (SessionStart hook) | ~10s (PostToolUse, failures only) |
| recall (minimal history only) | ~2s | 0 |

The `--minimal` install skips PostToolUse hooks and disables per-command failure tracking, cutting overhead significantly.

---

## Verdict

| Use case | Best tool |
|----------|-----------|
| Project rules and conventions | CLAUDE.md / AGENTS.md |
| Domain knowledge, strategic context | Native auto-memory (MEMORY.md) |
| Session history and search | recall |
| Recurring failure patterns | recall |
| Multi-platform unified history | recall (only option) |
| Zero overhead, zero maintenance | Native instruction files only |
| Resume specific past session | `claude -r` / `codex resume` (native) |
| Approved learnings loaded every session | recall (`/recall memory sync`) |

The ideal setup: instruction files for rules, native auto-memory for strategy, recall for mechanics — and `/recall memory` to feed what recall distills up into the native layer, so the knowledge you approved is loaded automatically rather than looked up.
