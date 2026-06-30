# recall — Named Restart Sessions (design)

**Date:** 2026-06-25
**Status:** Approved design, pending implementation plan
**Scope:** Scope 1 of 2. Scope 2 (RAG/embeddings restart-context reconstruction) is a
separate follow-on spec, sequenced on top of the v3 index Tier 2 work.
**Relates to:**
- `docs/superpowers/specs/2026-06-21-recall-command-grammar-design.md` (the `restart → load`
  rename and the `save`/`load`/`resume` split)
- `docs/plans/2026-06-21-recall-index-format-spec.md` (the v3 `recall.db` / FTS5 index;
  embeddings are its deferred Tier 2)

## 1. Goal

When you restart a recall checkpoint, the new session should carry a meaningful **name** —
either one you gave at save time (`/recall save <name>`) or the name your original Claude
session already had. The name then shows in the Claude prompt box, the `/resume` picker, and
the terminal title, and makes the checkpoint findable by name.

This is a small, self-contained change to the **save/restart internals**. It does not touch
search, indexing, or ranking, and is independent of the pending `restart → load` rename.

## 2. Background (verified during brainstorming)

- **The storage hook already exists.** `entry_session_name()` in `bin/recall-restart.py`
  (~lines 94–104) already resolves a restart's name token as `entry['name']` →
  `prompt_file` stem → `summary` slug. Nothing in the codebase ever writes `entry['name']`.
  This feature fills that field.
- **Where a Claude session's user-given name lives.** The Claude transcript
  (`~/.claude/projects/<folder>/<uuid>.jsonl`) contains `custom-title` lines, e.g.
  `{"type":"custom-title","customTitle":"auth-refactor","sessionId":"…"}`. recall reads none
  of these today. `ai-title` (auto-generated) and `agent-name` also exist.
- **Codex root sessions have no user-given name.** `session_meta.payload` only carries
  `agent_nickname` for *subagents*; top-level `cli` sessions have `agent_nickname = None`
  (verified across local rollouts).
- **Naming a live session is first-class and verified (local CLI v2.1.191).**
  `claude -n/--name <name>` — *"Set a display name for this session (shown in the prompt
  box, /resume picker, and terminal title)."* A named session can also be resumed by name
  (`claude --resume <name>`).
- **A fresh process is the only clean-context path that is also auto-nameable.** The
  SessionStart `hookSpecificOutput.sessionTitle` field is documented as *"ignored on `clear`
  and `compact`"*, so an in-session `/clear` restart cannot be auto-named. A clean-context
  restart therefore must be a fresh `claude` process named with `-n`.

## 3. Decisions (locked during brainstorming)

1. **Auto-name source = `customTitle` only.** A session is "named" if it has a user-given
   `customTitle`. `aiTitle` is *not* used (it is auto-generated, not user-chosen). When there
   is no `customTitle`, naming falls back to today's behavior (the summary slug).
2. **Clean restart = a fresh `claude` process named via `-n`.** Implemented by enhancing the
   existing launch path; the launched session opens in a **new Terminal window** (today's
   AppleScript mechanism). True same-window relaunch is out of scope (it cannot be driven from
   inside a running session without extra machinery).
3. **The clean named restart is the `--launch` variant.** The grammar's plain restart
   ("load the checkpoint into the *current* session") is left unchanged; `--launch` / `-l`
   becomes the fresh, named, clean-context restart.
4. **Live naming is Claude-only.** Codex root sessions have no user title, so a codex
   `/recall save` keeps its summary-slug name. An explicit `/recall save <name>` still records
   a name for a codex checkpoint (used for display and restart-by-name), but no codex live
   session title is set.
5. **Independent of the `restart → load` rename.** All changes live in the backing scripts
   (`bin/recall-save.py`, `bin/recall-restart.py`), which both `restart` and the future `load`
   verb route to. This feature is verb-name-agnostic.

## 4. Behavior

### 4.1 `save`

| Invocation | Result |
|---|---|
| `/recall save` | Checkpoint as today. The entry is **named** from the current session's `customTitle` if present; otherwise the existing summary-slug name (unchanged behavior). |
| `/recall save <name>` | Checkpoint named `<name>`. An explicit name always wins over the session's `customTitle`. |

**Name-resolution order at save time:**
1. Explicit `<name>` argument, if given.
2. Else the current Claude session's latest `customTitle` (Claude only).
3. Else the existing summary-slug fallback (today's behavior; also the codex path).

The resolved name is stored on the restart entry (see §6) and reused at restart time.

### 4.2 Dedup

Restart-by-name must stay unambiguous. When the resolved name would resolve to the **same
lookup token** as an existing restart entry for this project, append a short unique id:

```
auth-refactor          (first checkpoint)
auth-refactor-a3f9     (second checkpoint that resolved to the same name)
```

- The suffix is a short token derived from the new entry's own unique `id` (e.g. its first
  4 characters), chosen so the resulting lookup token is unique among existing entries; if a
  4-char suffix still collides (rare), it is lengthened until unique.
- Dedup is scoped to **this project's** restart entries (`agents.json`).

### 4.3 Restart (`load --launch` / `restart --launch`)

- The launch command changes from `cat <prompt> | claude` to
  `cat <prompt> | claude -n "<name>"`, where `<name>` is the entry's resolved name.
- The name value is shell-quoted/escaped safely (names may contain spaces or shell
  metacharacters).
- The plain (non-`--launch`) restart is unchanged: it still loads the checkpoint into the
  current session and does not rename anything.
- Native `resume` (`claude --resume`) is untouched — a resumed session already carries its
  own stored title.

## 5. Name capture

- A small helper — `read_session_title(transcript_path)` — scans a Claude transcript and
  returns the **most recent** `custom-title` line's `customTitle` (or `None`). Suggested home:
  `lib/shared.py`.
- `bin/recall-save.py` calls this against the current session's transcript at save time, so
  the name reflects the title as it stands when you checkpoint (not a possibly-stale index).
- **Codex:** no `custom-title` exists; the helper returns `None` and the summary-slug fallback
  applies. (We deliberately do not use `agent_nickname`, which only exists for subagents.)
- This feature does **not** add the title to the search index/sidecars; indexing the title for
  display in `/recall recent`/search is a possible later enhancement, out of scope here.

## 6. Data model

- The resolved, human-readable name is stored on the restart entry as `entry['name']` (a key
  `cmd_save()` does not write today).
- The restart-by-name **lookup token** stays slug-based and case-insensitive, via the existing
  `entry_session_name()` resolution. Dedup (§4.2) guarantees the token is unique.
- Exact field layout — a single readable `name` with a derived/deduped lookup token, vs.
  storing the deduped token alongside — is an implementation detail for the plan. The spec
  requires only: the **display name** passed to `-n` is the readable chosen name, and the
  **lookup token** is unique.

## 7. Surfaces to change (for the implementation plan)

- **`bin/recall-save.py`** — read `customTitle` (via the §5 helper) for the current session;
  resolve the name (explicit arg → `customTitle` → summary slug); pass it through
  `register_restart()` (~lines 355–389) as a new `--name` argument, mirroring `--session-id`.
- **`bin/recall-restart.py`** —
  - `cmd_save()` (~lines 316–381): accept `--name`; apply dedup (§4.2); store `entry['name']`.
  - argparse setup (~lines 737–791): add the `--name` option to the `save` subcommand.
  - `_build_launch_command()` (~lines 237–255): append `-n "<name>"` (safely quoted).
  - `entry_session_name()` (~lines 94–104): unchanged in spirit; it now actually receives a
    written `entry['name']`.
- **`skills/recall/SKILL.md`**, the save procedure, and **`commands/recall.md`** — document
  the `/recall save <name>` form and that `--launch` opens a fresh, named session.
- **Tests** — see §8.

*Optional, low-cost touch:* `cmux_register_recall()` in `bin/recall-save.py` (~line 434)
currently sets the cmux surface name to `"Recall: {summary}"`; it could use the resolved
session name when present (`"Recall: {name}"`). Listed in open questions, not required.

## 8. Testing

- **Name capture — Claude with `customTitle`:** `/recall save` records the `customTitle` as
  the entry name.
- **Name capture — Claude without `customTitle`:** falls back to the summary slug (no
  regression).
- **Explicit name:** `/recall save my-name` records `my-name`; explicit beats `customTitle`.
- **Dedup:** two checkpoints resolving to the same name produce distinct, unique lookup
  tokens (`name`, `name-<id>`); restart-by-name resolves each unambiguously.
- **Launch command:** `_build_launch_command()` emits `claude -n "<name>"` with correct
  quoting for names containing spaces/metacharacters.
- **Codex fallback:** a codex `/recall save` records the summary-slug name; an explicit
  `/recall save <name>` is honored for display/lookup.
- Existing save/restart tests continue to pass (no behavior change to plain restart or
  native resume).

## 9. Out of scope → Scope 2

- Reconstructing restart context via RAG over `recall.db` + embeddings (v3 Tier 2).
- Any change to search, indexing, ranking, or the v3 migration.
- Same-window (non-new-window) clean restart.
- Setting a live session title via the SessionStart `sessionTitle` hook (the `-n` launch flag
  covers every path recall controls; the hook would only add value for sessions recall does
  not launch — an edge case not worth the marker/correlation machinery now).

## 10. Risks & open questions

- **Readable name vs. slug for the display name.** §6 keeps the readable name for `-n`. If we
  instead standardize restart names as slugs (`auth-refactor` rather than `Auth Refactor`),
  the dedup suffix reads more cleanly but we lose the original casing/spacing. Decide in the
  plan; default is "readable name to `-n`, slug only for the lookup token."
- **Default vs. `--launch` (confirm).** Decision 3 keeps the *default* restart as
  load-into-current and makes `--launch` the clean named restart. If the intent is for
  clean-context to be the **default** restart, that is a change to the approved grammar's
  `load` semantics and should be folded back into the grammar spec.
- **Name quoting in the launch command.** The AppleScript + shell path that builds
  `cat … | claude -n "<name>"` must escape the name correctly; this needs an explicit test.
- **Codex launch path.** `_build_launch_command()` currently always invokes `claude`. Codex
  restart naming is therefore display/lookup-only regardless; if codex restarts should launch
  a codex process, that is a separate concern unaffected by this spec.
- **cmux surface name (optional).** Whether to also feed the resolved name into the cmux
  surface (`"Recall: {name}"`) is a nice-to-have; left as an optional plan item.
