# Test Catalogue

Every test module under `tests/`, in user-scenario (gherkin) language, organized
by **surface** — the part of recall that breaks if the module goes red.

UserHappy's Playwright catalogue groups by *run category* because its specs
differ by cost: hermetic mocks vs. real deployed hosts. recall's suite is one
kind of test — fast, hermetic, no network, ~6s for the whole thing — so speed is
not a useful axis here. What is useful is **blast radius**: when `@capture` goes
red the index stops being written and everything downstream is quietly wrong;
when `@sync` goes red an optional feature is broken and nothing else is. That is
the axis this catalogue uses.

## Surfaces — what breaks when this goes red

| Tag | Surface | What a failure means | How to run |
|-----|---------|----------------------|------------|
| `@capture` | Hooks that write the index | Sessions stop being recorded, or are recorded wrong. Everything downstream inherits the damage silently. | `pytest -m capture` |
| `@recall` | Reading the index back | Search, `last`, `failures`, stats, and SessionStart context are wrong or missing. The index is fine; you just can't get at it. | `pytest -m recall` |
| `@restart` | Save + restart checkpoints | The core loop — the thing recall exists for — fails at the moment the user needs it most. | `pytest -m restart` |
| `@knowledge` | Failures → learnings → SOPs | Junk reaches the review queue, or real guidance is dropped. Corrupts what recall claims to know. | `pytest -m knowledge` |
| `@memory` | Native memory bridge | recall writes into Claude Code's own config directory. A failure here can damage files recall does not own. | `pytest -m memory` |
| `@sync` | Optional cross-machine sync | An opt-in feature is broken. Nothing else is affected. | `pytest -m sync` |
| `@platform` | Paths, worktrees, packaging, dispatch | recall resolves the wrong project, or does not install/run at all. | `pytest -m platform` |

The whole suite is `pytest tests/ -q`. There is no slow tier to skip.

## Maintaining this catalogue

- Every test module belongs to exactly one surface. Add it here in the same
  change that adds the module.
- Keep entries at the behaviour level. `Feature` names the capability;
  `Scenario` names what a user or operator can do, or what invariant is
  protected — not the name of the assertion.
- `tests/test_catalogue.py` is the executable gate. It fails if a module is
  missing, listed twice, listed under two surfaces, or listed but absent from
  disk. The catalogue cannot drift from the suite without turning the suite red.
  It runs as part of `pytest tests/`, and in CI via `.github/workflows/test.yml`
  on every push and pull request — so a drifted map fails the build, not just a
  local run.
- The surface tags are applied automatically from this file by
  `tests/conftest.py`, so `pytest -m memory` works without touching any module.
  This file is the single source of truth for that mapping.
- List before relying on a tag as a gate: `pytest -m capture --collect-only -q`.

---

## @capture — hooks that write the index

```gherkin
# test_session_end.py
Feature: Indexing a Claude Code session when it ends
  Scenario: A finished transcript becomes an index entry with its messages, commands, and failures
  Scenario: Bash commands are extracted from tool calls, with exit codes and error text preserved
  Scenario: Failing commands are categorized (not_found, permission_denied, python_error, …) so patterns can be counted
  Scenario: A session summary is derived from what the user actually asked for
  Scenario: The index is pruned to a bounded size, and old per-session detail files are cleaned up
  Scenario: The hook identifies the current session unambiguously rather than guessing at the newest file
  Scenario: A corrupt or half-written index is never made worse by the write that follows it

# test_codex_session.py
Feature: Indexing a Codex CLI session from its real rollout JSONL
  Scenario: A real Codex rollout parses into the same shape a Claude session produces
  Scenario: Shell calls and their exit codes survive the format difference
  Scenario: The most recent rollout for this working directory is the one selected

# test_codex_session_end.py
Feature: Codex session-end utilities
  Scenario: Exit codes are recovered from Codex's command output shape
  Scenario: Errors are categorized identically to the Claude path, so one index holds both
  Scenario: Summaries, pruning, and detail-file writes behave the same for Codex sessions
  Scenario: Index writes are atomic — an interrupted save does not truncate the index

# test_bash_failure.py
Feature: Catching failing bash commands as they happen
  Scenario: A failing command is matched against known SOP patterns and the fix is surfaced immediately
  Scenario: An unmatched failure is recorded without inventing guidance for it
  Scenario: Project SOPs override global ones of the same name
  Scenario: Repeated failures accumulate state across a session without unbounded growth
  Scenario: Long command output is truncated before it reaches the index

# test_session_jobs.py
Feature: Durable SessionEnd indexing queue
  Scenario: SessionEnd enqueues metadata only, so it returns inside the host's short shutdown budget
  Scenario: Draining a queue commits each job exactly once, even after a crash mid-job
  Scenario: Two sessions ending at once each index their own exact transcript, never each other's
  Scenario: Only one worker can claim a job; a stale claim is recovered without clobbering pending work
  Scenario: A missing source file fails terminally instead of retrying forever; transient failures back off
  Scenario: Old receipts and logs are pruned while active jobs are kept

# test_hook_config.py
Feature: Hook installation wiring
  Scenario: Installed hooks invoke the wrapper scripts, not the Python files directly
  Scenario: The wrapper scripts are executable as shipped
  Scenario: The SessionEnd wrapper only enqueues durable work — it never indexes inline
```

## @recall — reading the index back

```gherkin
# test_recall_sessions.py
Feature: The /recall read surface
  Scenario: Recent sessions list with summaries, counts, and dates
  Scenario: `last` shows full detail from the previous session
  Scenario: Free-text search ranks matches across summaries, messages, commands, and failures
  Scenario: Quoted literals and slash-delimited regex search precisely rather than fuzzily
  Scenario: `failures` groups recurring error patterns with counts and last occurrence
  Scenario: `knowledge` shows what recall has learned, and `stats` shows what has been used
  Scenario: `cleanup` analyses the index and prunes noise, sensitive data, and duplicate failures
  Scenario: Export and import round-trip an index without losing entries
  Scenario: Every subcommand degrades gracefully when no index exists yet

# test_recall_format.py
Feature: Output formatting shared by the Rust and Python backends
  Scenario: Dates render relatively and consistently wherever they appear
  Scenario: Search-term matching behaves identically across query forms
  Scenario: Failure and stats output render the same regardless of which backend produced them

# test_text_rank.py
Feature: Local extractive ranking — no model call
  Scenario: Stop words are dropped and repeated actionable terms rank highest
  Scenario: Spinner and status noise is stripped without eating prose that mentions it
  Scenario: Ratified decisions outrank routine activity when a summary must choose
  Scenario: A query orders the most relevant text first
  Scenario: Slugs derived from text are short, safe, and stable

# test_session_start.py
Feature: SessionStart context injection
  Scenario: Elapsed time renders as human-readable "how long ago"
  Scenario: The previous session's context is formatted for injection at the top of a new session

# test_session_start_helpers.py
Feature: SessionStart helper resolution
  Scenario: Today's sessions across projects are collected for the picker
  Scenario: A project's short display name is derived from its path
  Scenario: The picker renders even when the default path holds nothing

# test_session_picker.py
Feature: Choosing among today's sessions
  Scenario: Sessions from today are gathered across every indexed project
  Scenario: Each entry shows a readable project name rather than a path slug
  Scenario: The picker formats a numbered, selectable list
```

## @restart — save and restart the core loop

```gherkin
# test_recall_save.py
Feature: Saving the current session as a restart briefing
  Scenario: The briefing is built from local extracts and ranking, not a transcript dump
  Scenario: Referenced paths are collected and de-duplicated
  Scenario: A restart is registered with a project-relative prompt path so it survives a move
  Scenario: Auto platform detection picks the agent with the freshest session evidence
  Scenario: The exact current Claude transcript is indexed — an ambiguous match is skipped unless a session id proves it
  Scenario: A name given by the user wins; otherwise the session title, otherwise a summary slug
  Scenario: Saving from a nested directory canonicalizes to the repo root
  Scenario: A cmux resume checkpoint is captured when one is available

# test_recall_restart.py
Feature: Listing, loading, and launching saved restarts
  Scenario: Restarts list, summarize compactly, and load by number, name, or fuzzy text
  Scenario: `--launch` opens a restart in a separate window as a fresh named session
  Scenario: `delete` removes both the registry entry and the stored prompt file
  Scenario: Duplicate named restarts collapse rather than accumulating
  Scenario: Parent and child projects are grouped so related restarts appear together
  Scenario: Ticket ids and themes are extracted to label a restart meaningfully
  Scenario: A restart name can never inject shell into the launch command

# test_recall_save_eval.py
Feature: A/B logging of local vs. LLM restart summaries
  Scenario: Both candidates are written with distinguishable prompt paths
  Scenario: Each comparison appends one JSONL entry recording prompt statistics
  Scenario: Promoting the LLM winner updates the matching registry entry, and leaves it alone when nothing matches
```

## @knowledge — failures become guidance, or are rejected

```gherkin
# test_extract_knowledge.py
Feature: Proposing learnings from what went wrong in a session
  Scenario: A failure followed by a working variant is proposed only when the error has a nameable class
  Scenario: Two commands sharing a first token are not treated as evidence of a fix
  Scenario: A "fix" that failed again later is not proposed, because nothing was resolved
  Scenario: A recurring failure becomes a learning only when a matching SOP supplies the remedy
  Scenario: Recurrences with no known remedy stay in failure patterns instead of masquerading as knowledge
  Scenario: Error messages map to stable categories used across the whole pipeline

# test_knowledge.py
Feature: The learning lifecycle — propose, review, approve, reject
  Scenario: A proposal that cannot state a reusable rule never reaches the review queue
  Scenario: Approving moves a learning into the durable set; rejecting tombstones it so it is not re-proposed
  Scenario: A genuinely new failure with the same title is still proposable after an older one was rejected
  Scenario: Learnings are grouped into buckets, per project, with a sensible default
  Scenario: Knowledge renders as a readable summary, bucketed or flat

# test_recall_learn.py
Feature: Reviewing pending learnings
  Scenario: Pending learnings display grouped by bucket with their source and proposed fix
  Scenario: Approve one, approve all, or reject one by index
  Scenario: `--prune` reports approved learnings that state no reusable rule, and removes them only with `--yes`
  Scenario: Approving does not write to native memory unless the project opted in
  Scenario: Opting in still does not let recall create a memory directory that does not exist

# test_setup_buckets.py
Feature: Bucket configuration for grouping learnings
  Scenario: Existing projects are discovered and offered as buckets
  Scenario: An existing configuration is loaded rather than overwritten
```

## @memory — writing into surfaces recall does not own

```gherkin
# test_native_memory.py
Feature: Promoting approved knowledge into Claude Code's auto-memory directory
  Scenario: Approved learnings become feedback memories and SOPs become reference memories
  Scenario: Only durable guidance is promoted; incident records are held back with a stated reason
  Scenario: A pinned project playbook carries the full text of every promoted rule into every session
  Scenario: recall claims at most one pin and refuses to pin at all when the user's four are spent
  Scenario: Rendering is deterministic, so an unchanged sync never rewrites a file or moves its mtime
  Scenario: Files and index pointers recall did not write are preserved verbatim, including position
  Scenario: A hand-edited promoted file is detected by hash and is neither overwritten nor pruned
  Scenario: Prune never deletes a file written by another recall installation
  Scenario: Content that looks like a credential is never written
  Scenario: A dry run predicts exactly what a real sync would do
  Scenario: Clearing removes everything recall promoted and nothing else

# test_memory_targets.py
Feature: The Codex owned-region adapter
  Scenario: Promoted knowledge is written as a marker-fenced block in the project's AGENTS.md
  Scenario: Content above and below the fence survives every rewrite byte for byte
  Scenario: Re-running replaces the block in place rather than appending a second one
  Scenario: The block respects a byte budget and reports whole entries it could not fit
  Scenario: recall will not create an AGENTS.md that does not already exist
  Scenario: Clearing removes the block and leaves the user's file otherwise untouched
  Scenario: The Codex target shares the promotion gate, so junk never reaches AGENTS.md either
```

## @sync — optional cross-machine sync

```gherkin
# test_sync.py
Feature: The sync engine and its provider interface
  Scenario: Files are gathered by category, honouring include flags and .recallignore
  Scenario: Every gathered file is secret-scanned before it can leave the machine
  Scenario: An unknown provider name fails loudly rather than silently doing nothing

# test_sync_config.py
Feature: Sync configuration
  Scenario: Configuration loads from YAML, with an environment override for the repo
  Scenario: A missing, empty, or corrupt config disables sync instead of crashing
  Scenario: The provider is inferred from the remote URL, defaulting to GitHub

# test_sync_git.py
Feature: Git sync provider
  Scenario: Push, pull, and status operate against a git remote
  Scenario: Initialization falls back gracefully when a clone fails, and is a no-op when already set up
  Scenario: Push falls back across branch names when the first attempt is rejected
  Scenario: Pulled dotfiles are skipped rather than written

# test_sync_cloud.py
Feature: Cloud sync provider
  Scenario: Push, pull, and status operate against the cloud endpoint
  Scenario: Rate limiting stops the push; storage-full and HTTP errors are recorded per file
  Scenario: A failed listing or file fetch degrades to an empty result rather than an exception

# test_sync_hooks.py
Feature: Sync triggered from session end
  Scenario: A push runs on session end only when configured, automatic, and not in manual mode
  Scenario: Strict secret scanning blocks dirty files from being pushed at all
  Scenario: A pull can never write outside recall's own sync categories
  Scenario: Path traversal, settings.json overwrite, and stray dotfiles from a remote are all rejected
  Scenario: Legitimate category paths still land when they arrive alongside blocked ones

# test_sync_format.py
Feature: The on-the-wire YAML format
  Scenario: Restarts, learnings, SOPs, session metadata, and agent configs each serialize predictably
  Scenario: Filenames are dated, slugged, and truncated to a safe length

# test_sync_ignore.py
Feature: .recallignore
  Scenario: Patterns are parsed, with comments and blank lines ignored

# test_sync_scan.py
Feature: Secret scanning before anything leaves the machine
  Scenario: AWS keys, API tokens, GitHub tokens, bearer tokens, connection strings, and private keys are caught
  Scenario: Clean content passes untouched, and an unreadable file is skipped rather than fatal

# test_sync_state.py
Feature: Optimistic-concurrency sync so two machines cannot silently clobber a shared learning
  Scenario: A push carries If-Match with the base it edited from, or create-only when it has no base
  Scenario: A 412 surfaces as a conflict with no base recorded, rather than overwriting the other machine's edit
  Scenario: A pull records the served content_sha256 as the base for the next push
  Scenario: A server secret rejection (422) surfaces per file, and only real hex digests ever enter state
```

## @platform — where recall thinks it is, and whether it runs at all

```gherkin
# test_platform.py
Feature: Detecting the host agent
  Scenario: Claude Code and Codex are detected from the variables each injects
  Scenario: An unrecognized environment falls back safely rather than guessing
  Scenario: Commands render as /recall or $recall to match the host's surface

# test_shared_io.py
Feature: Index and session-detail I/O
  Scenario: A missing index is created empty on demand; a corrupt one does not take the process down
  Scenario: Saving is atomic, so an interrupted write cannot truncate the index
  Scenario: Session details and agent records round-trip
  Scenario: A session's title is read from its transcript when one was recorded

# test_worktree_resolution.py
Feature: Git worktrees resolve to one project
  Scenario: A worktree resolves to its main repo so all worktrees share one index
  Scenario: Resolution works from the registry, from the path shape, and falls back when neither applies
  Scenario: The resolved folder and the literal folder are both available, because Claude Code uses the literal one

# test_worktree_registry.py
Feature: The worktree registry
  Scenario: Worktrees are recorded against their main repo and looked up by path
  Scenario: Stale worktrees are pruned and empty projects removed
  Scenario: Paths normalize to Claude Code's project-folder convention

# test_recall_wrapper.py
Feature: The bin/recall shell dispatcher
  Scenario: Subcommands route to the right script with the project path preserved
  Scenario: A trailing --launch flag is accepted in either position
  Scenario: Codex invocations are told to use $recall, not a slash command

# test_plugin_packaging.py
Feature: What actually ships in the plugin
  Scenario: The Codex manifest exposes the recall skill and carries its required interface fields
  Scenario: The packaged SessionEnd path is the durable enqueue path, not inline indexing
  Scenario: Dev-cache sync resolves the current installed version

# test_rust_python_parity.py
Feature: The Rust fast path agrees with the Python backend
  Scenario: Both backends produce identical failure output for the same fixture index

# test_catalogue.py
Feature: This catalogue stays true
  Scenario: Every test module is listed exactly once, under exactly one surface
  Scenario: Every module listed here exists on disk
  Scenario: Each surface tag in the table has at least one module behind it
```
