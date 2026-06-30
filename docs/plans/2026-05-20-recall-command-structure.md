# /recall Command Structure

## Goal

Keep recall easy to invoke as one command:

- `/recall save`
- `/recall restart`
- `/recall '.p8'`
- `/recall /*\.p8/`
- `/recall learn`
- `/recall sops ?`
- `/recall help`

## Current Claude Code Evidence

Official Claude Code docs now describe `skills/` as the preferred plugin component for new command-like workflows. `commands/` still works, but it is the legacy flat Markdown format.

Relevant docs:

- https://code.claude.com/docs/en/plugins
- https://code.claude.com/docs/en/plugins-reference
- https://code.claude.com/docs/en/slash-commands
- https://code.claude.com/docs/en/agent-sdk/plugins

Key constraints from those docs:

- Plugin components live at the plugin root; only `.claude-plugin/plugin.json` belongs under `.claude-plugin/`.
- Plugin `skills/<name>/SKILL.md` entries can be invoked as slash commands and can receive `$ARGUMENTS`.
- Plugin skills are namespaced as `plugin-name:skill-name` to avoid conflicts.
- Personal or project skills/commands can provide a short unnamespaced command.
- If a skill and command share a name, the skill takes precedence.
- `bin/` is the right place for bundled scripts that the skill executes.

## Decision

Use one canonical plugin skill:

```text
skills/recall/SKILL.md
```

That skill is the only real dispatcher. It parses `$ARGUMENTS` and lazy-loads procedure files for workflows that need model judgment:

```text
skills/recall/procedures/save.md
skills/recall/procedures/restart.md
skills/recall/procedures/learn.md
```

Keep broad lookup and display behavior script-backed:

```text
bin/recall-sessions.py
bin/recall-save.py
bin/recall-restart.py
bin/recall-learn.py
```

Keep `commands/recall.md` only as legacy flat-command documentation/compatibility. Do not add separate plugin skills named `save`, `restart`, or `learn`; that would create `/recall:save` style entries and work against the desired `/recall <subcommand>` surface.

## Short `/recall`

Claude Code namespaces plugin skills, so the plugin-provided command is reliably available as:

```text
/recall:recall
```

The easy `/recall` spelling should stay an opt-in personal alias installed by:

```text
/recall:install-alias
```

That alias lives at:

```text
~/.claude/commands/recall.md
```

and invokes the `recall:recall` skill with the full argument string.

## Search Rules

Unknown subcommands are search queries. This keeps the command surface small and lets `/recall sops` work without new command registration.

Literal search:

- `/recall sops`
- `/recall sops ?` ignores the standalone question mark.
- `/recall '.p8'` strips outer quotes and searches for `.p8`.

Regex search:

- Slash-delimited queries are treated as Python regex search.
- `/recall /.*\.p8/` matches `.p8` mentions.
- `/recall /*\.p8/` is accepted as forgiving shorthand for the same common search.

## Rationale

This keeps always-on plugin context small, avoids duplicated dispatch logic, preserves the simple user-facing command, and lets heavy behavior stay in deterministic local scripts instead of requiring the model to interpret session history.
