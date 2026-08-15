# Recall — Durable Deferred Session Indexing

**Date:** 2026-07-28
**Status:** Proposed implementation spec
**Motivation:** Codex clamps `SessionEnd` hooks to three seconds. Recall's
current SessionEnd work can parse a full transcript, extract learnings, clean
history, and sync. The wrapper's `nohup` approach avoids some shutdown
cancellations, but it is not a durable work queue and it can select the wrong
transcript by modification time.

## 1. Goal

Make automatic Recall indexing reliable after a Claude Code or Codex session
ends without asking the session-end hook to do more than a bounded durable
handoff.

The new flow must preserve the same useful outputs as current synchronous
indexing:

- a session detail file and a lightweight index summary;
- failure-pattern and skill-usage updates;
- local heuristic learning proposals;
- best-effort configured sync; and
- manual `/recall save` / `$recall save` behavior.

It must not remove or weaken `bin/recall-save-eval.py`'s LLM A/B restart-prompt
evaluation loop. That evaluator remains a separate, intentional quality loop.

## 2. Context and constraints

### The current failure mode

`hooks/hooks.json` declares a 30-second `SessionEnd` timeout. Codex supports
only three seconds for that lifecycle event and logs a timeout-clamping warning.
The current `hooks/scripts/session-end` wrapper tries to solve the problem by
running `session-end.py` under `nohup`.

That is insufficient because:

1. a detached child is not a durable job record or retry mechanism;
2. it can lose its executable path when a plugin cache changes;
3. it gives no user-visible state when indexing fails; and
4. the legacy Claude parser's fallback to the newest transcript is unsafe with
   concurrent sessions or worktrees.

The Codex parser currently has a similar `--latest` convenience path. It is
acceptable for an explicit manual recovery command, but it must not be used by
automatic SessionEnd processing.

### Hard constraints

1. The SessionEnd hook has a three-second hard ceiling in Codex. Its normal
   work must be a single small metadata write; target p99 under 250 ms on a
   local disk.
2. A job must name the exact transcript/rollout it will index. Automatic work
   must never choose a different transcript based on mtime.
3. Queue files contain metadata only, never transcript content or credentials.
4. Existing `~/.claude/projects/<project>/` Recall storage remains canonical
   for indexes, session details, restarts, and per-project jobs. Do not store
   mutable state inside a plugin cache.
5. Index commits must be safe if a worker, `/recall save`, or a second session
   overlaps. Retrying a completed or half-completed job must not double-count
   failures or skill usage.
6. No privileged daemon or network service is required. macOS gets an optional
   user-scoped `launchd` runner; every platform retains a foreground drain
   command for diagnosis and recovery.

## 3. Decisions (locked)

### 3.1 Queue, not a detached process

The hook writes a durable queue job, returns the runtime-required empty/JSON
hook envelope, and exits. It must not use `nohup`, `&`, a pipe to a child
process, transcript parsing, extraction, cleanup, or sync.

The durable queue is the source of truth. A worker can be restarted at any
point; queued jobs survive a process crash, a session restart, and a laptop
sleep/wake cycle.

### 3.2 Exact transcript identity is mandatory

Every automatic job has an absolute `source_path`, `platform`, and
`project_dir`. The enqueue adapter validates that the source is a regular file
under its allowed platform session root before creating a job:

| Platform | Allowed source root | Parser |
| --- | --- | --- |
| Claude | `~/.claude/projects/` | refactored `session-end.py` parser |
| Codex | `~/.codex/sessions/` | refactored `codex_session_end.py` parser |

The adapter obtains that path from the platform SessionEnd event or an explicit
`RECALL_SESSION_FILE` value. Capturing and fixture-testing the exact event
fields is an implementation prerequisite. If a platform does not provide an
exact source path, the hook records a concise diagnostic and safely skips
enqueueing; it does **not** fall back to `--latest` or mtime discovery.

`--latest` stays available only as an explicit manual recovery action, clearly
labelled as potentially ambiguous.

### 3.3 Per-project queue layout

Add `get_session_jobs_dir(project_folder)` in `lib/shared.py`, returning:

```text
~/.claude/projects/<project-folder>/recall-jobs/
  pending/
  running/
  completed/
  failed/
  logs/
```

The queue belongs beside the existing Recall index, not under the source clone
or `~/.codex/plugins/cache`. `completed` receipts are retained for seven days
and failed jobs for 30 days by default; pruning never deletes a pending or
running job.

### 3.4 Job schema v1

Write one JSON file named `<job-id>.json` with mode `0600`. Write through a
same-directory temporary file, `fsync`, then `os.replace` it into `pending/`.

```json
{
  "schema_version": 1,
  "id": "sha256(platform + NUL + canonical_source_path)[:32]",
  "platform": "codex",
  "source_path": "/Users/me/.codex/sessions/2026/07/28/rollout-abc.jsonl",
  "project_dir": "/Users/me/code/project",
  "project_folder": "-Users-me-code-project",
  "source_size": 12345,
  "source_mtime_ns": 1750000000000000000,
  "enqueued_at": "2026-07-28T15:00:00+00:00",
  "eligible_after": "2026-07-28T15:00:05+00:00",
  "attempts": 0,
  "last_error": null
}
```

The path-derived ID makes repeat enqueue calls for one transcript idempotent.
If `pending`, `running`, `completed`, or `failed` already contains the ID, the
enqueue succeeds as a no-op. A developer can retry a failed job explicitly;
that retains the same ID and increments `attempts`.

The source size and mtime are observations, not the identity. Before indexing,
the worker verifies the file still exists, remains within the allowed root, and
has been stable across two `stat` calls one second apart. If it is still being
written, it returns the job to `pending` with a short delay.

### 3.5 One-shot worker plus optional macOS scheduler

Implement `bin/recall-jobs.py` with these commands:

```text
recall jobs status [--project <dir>]
recall jobs drain [--project <dir>] [--max-jobs N] [--time-budget SEC]
recall jobs show <job-id>
recall jobs retry <job-id>
recall jobs install-daemon
recall jobs uninstall-daemon
```

`drain` is a one-shot process. It finds due jobs under
`~/.claude/projects/*/recall-jobs/pending`, claims a bounded number, processes
them, then exits. Its defaults are two jobs and a 60-second time budget so it
is quiet and does not compete with active coding work.

On macOS, `recall jobs install-daemon` installs a per-user LaunchAgent named
`com.ashrocket.recall-indexer` that invokes the stable source installation at
`~/.recall/bin/recall jobs drain --max-jobs 2 --time-budget 60` at load and
every 30 seconds. The installer must refuse to register a plugin-cache path;
users with only a plugin cache get the portable foreground command and clear
setup instructions instead. No `sudo`, system daemon, or remote API is used.

The implementation must document that the source installation (`~/.recall`) is
the stable worker location. A plugin refresh cannot invalidate a running
LaunchAgent.

### 3.6 Claim, retry, and failure behavior

The worker claims a job with an atomic rename from `pending/` to `running/`.
Only the process that wins the rename owns the job. A stale `running` job whose
lease exceeds five minutes is returned to `pending` on the next drain.

Expected transient failures use exponential backoff of 1, 5, 30, and 180
minutes, then daily. After ten attempts, move the job to `failed/` with its
last error and surface it in `recall jobs status`; do not discard it.

The following are terminal until explicit retry:

- source file is missing or outside its allowed root;
- malformed job JSON/schema;
- unsupported platform value; or
- unsupported source format.

The worker writes short diagnostics to `logs/<job-id>.log`, redacting home
paths only when a future privacy setting requires it and never logging
transcript content.

### 3.7 Idempotent index commit

Refactor the shared "parse then persist" code out of both current scripts into
a single indexing service with platform parser adapters. Suggested boundaries:

```text
lib/session_jobs.py       # schema, enqueue, claim, retry, status, cleanup
lib/session_indexing.py   # lock, parse dispatch, apply, atomic commit
lib/parsers/claude.py     # extracted from hooks/scripts/session-end.py
lib/parsers/codex.py      # extracted from hooks/scripts/codex_session_end.py
bin/recall-jobs.py        # CLI only
```

Add a per-project `recall-index.lock`, held with `fcntl.flock` around the
read-modify-write commit. Change `lib.shared.save_index` to write a temporary
file, `fsync`, and atomically replace `recall-index.json`.

The commit records the job ID in bounded `index["job_receipts"]` before the
file replacement. A retry that finds its receipt skips mutation and only moves
the job to `completed/`. The receipt must be retained longer than the longest
retry window (90 days is the initial policy).

`apply_indexed_session()` must be idempotent by session ID: it replaces the
session summary/details and replaces this session's failure-pattern
contributions rather than appending duplicates. Skill-usage accounting must
also be recomputed or delta-upserted safely so a crash after index commit cannot
increment a skill twice.

After the index commit succeeds, the worker may run local heuristic extraction,
periodic cleanup, and configured sync. Those are best-effort post-commit work:
their failures are logged but never roll back a successfully indexed session or
cause the transcript to be re-indexed.

### 3.8 Runtime hook contracts

`hooks/scripts/session-end` becomes a thin adapter over queue enqueue. Remove
the `nohup` and `RECALL_SESSION_END_INLINE` execution paths. It must preserve
the current stdout contract for each host:

- Claude SessionEnd: no human output on stdout;
- Codex SessionEnd: only the minimal valid envelope required by the actual
  runtime contract; and
- both: diagnostics only on stderr and a zero exit for a non-fatal skipped
  enqueue.

`hooks/hooks.json` keeps `SessionEnd.timeout = 3`. The timeout is no longer a
promise that a full index completes; it is the honest budget for the enqueue.

`AGENTS.md`, `README.md`, onboarding, and the Recall skill must describe the
worker and its status command. Replace the AGENTS.md instruction to run
`codex_session_end.py --latest` at session end with exact-source enqueue when
available, plus `recall jobs drain` as a manual recovery path.

## 4. End-to-end flow

```text
SessionEnd event
  -> adapter validates exact transcript path and writes pending/<id>.json
  -> hook returns in under 3 seconds
  -> launchd interval (or `recall jobs drain`) claims the job
  -> worker waits for source stability and parses the exact file
  -> locked, atomic, idempotent index commit with job receipt
  -> details + summary visible to normal Recall commands
  -> best-effort extraction, cleanup, and sync
  -> completed/<id>.json retained for audit; failed jobs remain inspectable
```

## 5. Compatibility and migration

1. Ship the queue library and CLI before changing the hook wrapper.
2. Keep both parser command paths working during the refactor:
   `session-end.py --session-file <path>` and
   `codex_session_end.py --file <path>` become thin compatibility wrappers over
   the shared indexing service.
3. Existing indexes need no format migration beyond an optional empty
   `job_receipts` map created on first write.
4. On first worker run, create queue directories lazily with `0700` directory
   permissions. Do not scan historical transcripts or retroactively enqueue
   them automatically.
5. Remove the old `nohup` wrapper behavior only after the queue enqueue and
   foreground drain tests pass. A versioned migration note must tell users how
   to install the macOS worker or run a manual drain.

## 6. Explicit non-goals

- No cloud queue, database server, privileged helper, or background process
  tied to an active Codex/Claude session.
- No LLM required for queueing or indexing.
- No semantic change to Recall ranking, search, saved restarts, or the LLM A/B
  restart-prompt evaluator.
- No automatic guessing of a current transcript from modification time.
- No deletion of failed jobs, historical transcripts, or existing indexes as
  part of migration.

## 7. Implementation slices

### Slice A — durable queue primitives

- Add path helpers and job schema validation.
- Implement atomic enqueue, claim, stale-lease recovery, status, retry, and
  retention cleanup.
- Add tests for file modes, atomic/no-partial writes, idempotent enqueue,
  malformed jobs, and concurrent claimers.

### Slice B — exact-source adapters

- Capture real Claude and Codex SessionEnd input fixtures.
- Implement platform adapters that derive `source_path`, `project_dir`, and
  the required hook stdout envelope.
- Remove all automatic mtime/latest fallback from the hook path.
- Test two concurrent sessions in one project; each must enqueue its own
  source or safely skip, never cross-index.

### Slice C — shared idempotent index service

- Extract parser logic without changing its outputs.
- Add locking, atomic index writes, receipts, and session upsert behavior.
- Route manual save and both legacy scripts through it.
- Test a simulated crash after the index replacement but before the job move;
  draining again must not change counts.

### Slice D — worker and macOS scheduling

- Add bounded foreground `drain` and status/show/retry commands.
- Add stable-source LaunchAgent install/uninstall and plist tests.
- Test missing source, unstable source, transient failure/backoff, permanent
  failure, stale running recovery, and a successful end-to-end job.

### Slice E — docs, package, and release

- Update `hooks/hooks.json`, wrapper tests, AGENTS.md, skill instructions, and
  user-facing docs.
- Bump the plugin version, package the hook changes, refresh the active
  installed plugin only after source tests pass, and verify source/cache match.
- Keep unrelated checkout changes out of the release commit.

## 8. Acceptance criteria and verification

The work is done only when all of the following are true:

1. Starting Codex with Recall enabled no longer logs a SessionEnd timeout clamp.
2. A SessionEnd hook returns within three seconds while a deliberately slow
   parser still completes later through the queue worker.
3. Two overlapping Claude/Codex sessions cannot cause an automatic indexer to
   process the wrong transcript.
4. Killing the worker before, during, and after an index commit leaves either a
   pending/running job recoverable or one idempotent committed session—never
   a duplicate count or corrupt JSON index.
5. `recall jobs status` makes pending, running, completed, failed, retry time,
   and last error observable without reading raw files.
6. `recall jobs drain` works without a LaunchAgent; the installed user
   LaunchAgent invokes only a stable `~/.recall` source path.
7. Existing focused parser, save/restart, learning, sync, and A/B evaluator
   tests remain green, plus the new queue/worker tests.
8. A plugin install/update cannot silently restore a 30-second SessionEnd
   declaration or a `nohup`-based indexing path.

## 9. Risks to manage during implementation

- **Event schema uncertainty:** do not infer Codex or Claude event fields.
  Capture fixtures first and add a contract test for both adapters.
- **Index migration/concurrency:** a receipt without an atomic index write is
  not sufficient. Lock and replace must land with the receipt change.
- **Daemon path drift:** never register a LaunchAgent to a plugin-cache path.
- **Worker starvation:** queue status must expose a missing daemon and stale
  pending jobs; manual drain remains the recovery route.
- **Storage growth:** retain metadata receipts/logs with bounded cleanup, but
  never treat a source transcript or failed job as disposable during retries.
