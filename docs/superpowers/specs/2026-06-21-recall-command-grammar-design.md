# recall — Semantic Command Grammar (design)

**Date:** 2026-06-21
**Status:** Approved design, pending implementation plan
**Supersedes / extends:** `docs/plans/2026-05-20-recall-command-structure.md`

## 1. Goal

Give `recall` one consistent, self-documenting verb vocabulary so all ~17 existing
features are easy to find and invoke across Claude Code, Codex, and Gemini — without
adding new commands or changing what any feature does.

This is a **naming + grammar** change, not a feature change. The same scripts do the
same work; they are reached through a cleaner, fully-worded subcommand grammar.

## 2. Decisions (locked)

These were settled during brainstorming and are fixed inputs to the plan:

1. **Single dispatcher, not command-per-feature.** Keep one `/recall` surface
   (the canonical `recall:recall` skill, per the 2026-05-20 doc) with a redesigned
   subcommand grammar. Do **not** create `/recall:save`-style per-feature commands.
2. **Full words only.** Canonical verbs are whole words (`save`, `search`, …). No
   single-letter aliases (`s`, `?`, `l`) are introduced.
3. **Search stays dual-mode.** A bare unrecognized token is still a search term
   (`/recall jwt refactor`, `/recall /regex/`), **and** there is an explicit
   `search` verb for discoverability and verb-collision cases (`/recall search save`).
4. **Two clarity renames:** `list → recent`, `restart → load`. Old names remain as
   hidden, deprecated, back-compat aliases.

## 3. The verb taxonomy

Five semantic groups. One token = one idea.

| Group | Verb | Forms | Behavior | Backed by |
|---|---|---|---|---|
| **Browse** | `recent` | `/recall`, `/recall recent` | Recent sessions (also the no-arg home) | `recall-sessions.py` |
| | `last` | `/recall last` | Full detail of the previous session | `recall-sessions.py` |
| | `search` | `/recall search <term>` · `/recall <term>` · `/recall /regex/` | Ranked search; bare term or `/regex/` also search | `recall-sessions.py` |
| | `failures` | `/recall failures` | Recurring failure patterns + linked learnings | `recall-sessions.py` |
| | `stats` | `/recall stats` | Skill & learning usage analytics | `recall-sessions.py` |
| | `knowledge` | `/recall knowledge` | Loaded CLAUDE.md project knowledge | `recall-sessions.py` |
| **Continue** | `save` | `/recall save` | Checkpoint current work into a restart prompt | `recall-save.py` |
| | `load` | `/recall load [<n\|name>]` · `--launch <n\|name>` | List checkpoints; load one into the current session; `--launch` opens it in a new window | `recall-restart.py` |
| | `resume` | `/recall resume [<n>]` | List / launch native `claude --resume` sessions | `recall-restart.py` |
| **Curate** | `learn` | `/recall learn [approve\|reject …]` | Review pending learnings | `recall-sessions.py learn` |
| **Maintain** | `cleanup` | `/recall cleanup` | Analyze & prune the session index | `recall-sessions.py` |
| | `export` / `import` | `/recall export` · `/recall import` | Move the index between machines | `recall-sessions.py` |
| | `reset` | `/recall reset` | Wipe the index | `recall-sessions.py` |
| **Meta** | `help` | `/recall help [<verb>]` | Full help, or per-verb usage | dispatcher |

**Conceptual split that the renames buy us:**
- `save` ↔ `load` — write and reopen recall's own distilled **checkpoint** (portable,
  cross-tool, focused).
- `resume` — relaunch the **exact native session** via `claude --resume` (full
  fidelity, Claude-only, captured by cmux at save time).

`load` and `resume` are now clearly different actions; the old `restart` vs `resume`
near-synonym ambiguity is gone.

## 4. Grammar & conventions

1. **Reserved verbs win.** The 15 verbs in §3 (plus the hidden aliases in §5) are
   reserved. Any other first token is a **search term**. Searching for a word that
   collides with a verb uses the explicit form: `/recall search save`.
2. **Regex search** is slash-delimited (existing behavior, preserved):
   - `/recall /.*\.p8/` — Python regex search.
   - `/recall /*\.p8/` — forgiving shorthand for the same common case.
3. **Quote stripping** (existing, preserved): `/recall '.p8'` searches for `.p8`.
4. **Standalone `?` is ignored** in search args (existing, preserved):
   `/recall sops ?` searches `sops`.
5. **No-arg `/recall`** → `recent` sessions, followed by a one-line footer hinting the
   verb groups (Browse · Continue · Curate · Maintain · `help`). New, small addition
   to today's bare list; gives discoverability without requiring `help`.
6. **`help [<verb>]`** → full help, or usage for a single verb (`/recall help load`).
   Per-verb help is new.
7. **Flags** use long form with conventional short forms where they already exist:
   `load --launch` / `-l`; `learn` keeps its `approve`/`reject` flags.

## 5. Renames & backward compatibility

Two canonical renames, each with a **hidden, deprecated alias** that still routes to
the new verb:

| Old | New (canonical) | Alias behavior |
|---|---|---|
| `list` | `recent` | `list` still works; not advertised in help; emits nothing visible (silent) or an optional one-line deprecation note (decide in plan). |
| `restart` | `load` | `restart` still works; routes identically to `load`, including `--launch`. |

Rationale for shims: there is an existing user base, published docs, and possibly
user scripts referencing `list`/`restart`. Hidden aliases make the rename a soft
migration — nothing breaks the day this ships — and the aliases can be removed in a
later major version.

The `restart` procedure file is renamed to match the canonical verb:
`skills/recall/procedures/restart.md → skills/recall/procedures/load.md`
(the skill routes both `load*` and `restart*` to it).

## 6. One interface, three platforms

The grammar is defined **once**, at the `bin/recall <verb> [args]` layer. Every
platform reaches the same verbs:

- **Claude Code:** the `recall:recall` skill parses `$ARGUMENTS` and dispatches —
  `save*`/`load*`(+`restart*`)/`learn*` lazy-load their procedure files; everything
  else execs `bin/recall`. The opt-in `/recall` personal alias (via
  `recall:install-alias`) is unchanged.
- **Codex:** drives `bin/recall <verb>` via the skill and `hooks/scripts/`
  (`codex_session_end.py`, `session-start`).
- **Gemini:** hook-based, same `bin/recall <verb>` entry points (per `GEMINI.md`).

No per-platform verb drift: if a verb exists, it exists everywhere, because it lives
in `bin/recall`.

## 7. Argument hardening (bug fix folded in)

Today the Claude command passes `$ARGUMENTS` **unquoted** to the shell
(`${CLAUDE_PLUGIN_ROOT}/bin/recall "$PWD" $ARGUMENTS`). Search terms or `/regex/`
patterns containing shell glob metacharacters (`*`, `?`, `[`) can be expanded against
the current directory before `bin/recall` ever sees them — e.g. `/recall foo*bar`
silently becomes whatever `foo*bar` globs to.

The plan must make argument passing safe (proper quoting/escaping, or reading the raw
argument string) so search and regex queries are passed through literally, while still
supporting multi-word terms. This is the natural moment to close this latent bug,
since the search grammar is being formalized.

## 8. Surfaces to change (for the implementation plan)

- `skills/recall/SKILL.md` — routes: add `recent`, `load` (+ `restart` alias), keep
  `save*`/`learn*`; document the verb groups; reference `help <verb>`.
- `skills/recall/procedures/restart.md` → `load.md` (git mv; update internal refs).
- `bin/recall` (sh dispatcher) — case arms for `recent`/`load` and the `list`/`restart`
  aliases; `--launch`/`-l` under `load`; safe arg handling; `help <verb>` routing.
- `bin/recall-sessions.py` — accept `recent` (alias of `list`), `help [<verb>]`, and
  the no-arg footer hint; keep `list` working.
- `bin/recall-restart.py` — reached via `load`/`restart`; no behavior change required.
- `commands/recall.md` (legacy compatibility doc) — update examples to the new grammar.
- Docs: `README.md`, `AGENTS.md`, `GEMINI.md`, `ONBOARDING.md`, `docs/start.html`,
  `docs/examples.html`, `docs/comparison-vs-builtin-memory.md` — `list → recent`,
  `restart → load` in user-facing examples.
- Tests: any referencing `list`/`restart` verbs (e.g. `tests/test_session_picker.py`,
  `tests/test_session_start.py`) — cover both new verbs and the back-compat aliases.

## 9. Out of scope

- No new per-feature slash commands (`/recall:save`, etc.).
- No single-letter aliases.
- No change to what any feature does (indexing, ranking, save/restart internals).
- No change to the opt-in `/recall` personal-alias mechanism.

## 10. Risks & open questions

- **Doc churn.** `restart`/`list` appear across many docs and the microsite; the plan
  must update them consistently or the grammar and docs diverge.
- **Deprecation visibility.** Should the `list`/`restart` aliases be fully silent, or
  print a one-line "renamed to `recent`/`load`" note? (Lean silent to avoid noise;
  decide in plan.)
- **Arg-hardening regressions.** Changing `$ARGUMENTS` handling must preserve
  multi-word search, quote-stripping, the forgiving `/regex/` shorthand, and the
  ignored-standalone-`?` rule. These need explicit test coverage.
- **`help <verb>` source of truth.** Per-verb help text should be generated from a
  single verb table so help can't drift from behavior.
