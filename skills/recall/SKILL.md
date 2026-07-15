---
name: recall
description: Use when searching local recall session memory, saving or restarting checkpoints, showing recurring failures, or reviewing pending learnings.
version: 3.4.0
---

# recall — fast dispatch

Do not reason over session history in-model. Dispatch to local scripts and show their output.

## Routes

- `save*`: read `skills/recall/procedures/save.md`; pass everything after `save` as `$ARGUMENTS` (an optional restart name).
- `restart*`: read `skills/recall/procedures/restart.md`; pass everything after `restart` as `$ARGUMENTS`.
- `learn*`: read `skills/recall/procedures/learn.md`; pass everything after `learn` as `$ARGUMENTS`.
- everything else (`help`, empty, `list`, `last`, `failures`, `stats`, `cleanup`, `knowledge`, or an arbitrary search term / slash-delimited regex):

```bash
RECALL_ROOT=${CLAUDE_PLUGIN_ROOT:-}
if [ -z "$RECALL_ROOT" ]; then
  for candidate in "$HOME/.codex/plugins/cache/recall/recall/"*/bin/recall "$HOME/.claude/plugins/cache/recall/recall/"*/bin/recall; do
    [ -x "$candidate" ] || continue
    RECALL_ROOT=${candidate%/bin/recall}
    break
  done
fi
if [ -z "$RECALL_ROOT" ]; then
  echo "Could not locate a recall installation" >&2
  exit 1
fi
exec "$RECALL_ROOT/bin/recall" "$PWD" $ARGUMENTS
```

`bin/recall` uses the compiled Rust fast path when available and falls back to Python for unsupported or uncompiled paths.
