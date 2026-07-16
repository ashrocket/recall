# /recall restart — Resume a Saved Session

`$ARGUMENTS` is everything after `restart` from the original `/recall restart [...]` invocation.

## Setup

Resolve the install root once, the same way as every other recall route:
```bash
RECALL_ROOT=${CLAUDE_PLUGIN_ROOT:-}
if [ -z "$RECALL_ROOT" ]; then
  for base in "$HOME/.claude/plugins/cache/recall/recall" "$HOME/.codex/plugins/cache/recall/recall"; do
    [ -d "$base" ] || continue
    latest=$(ls -1 "$base" 2>/dev/null | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)
    [ -n "$latest" ] && [ -x "$base/$latest/bin/recall" ] && RECALL_ROOT="$base/$latest" && break
  done
fi
if [ -z "$RECALL_ROOT" ]; then
  echo "Could not locate a recall installation" >&2
  exit 1
fi
```

## Dispatch

By default, load restart prompts into the current session. Do not open separate Terminal/Claude windows unless `$ARGUMENTS` starts with `--launch` or `-l`.

**If** no argument or argument is **`list`**: List all saved restarts with their numbered position and named-session token.
```bash
python3 "$RECALL_ROOT/bin/recall-restart.py" list
```

**If** argument is **`summary`** or **`summarize`**: Show a compact numbered review list for selecting old restarts.
```bash
python3 "$RECALL_ROOT/bin/recall-restart.py" summary
```

**If** argument starts with **`delete`**, **`rm`**, or **`remove`**: Delete one saved restart by list number, exact name, or unique text match. Prefer a number from the current list or summary when pruning old prompts.
```bash
python3 "$RECALL_ROOT/bin/recall-restart.py" delete <number>
python3 "$RECALL_ROOT/bin/recall-restart.py" delete "<name-or-unique-text>"
```

**If** argument starts with **`--launch`** or **`-l`**: Open a separate Terminal/Claude window for that restart.
```bash
python3 "$RECALL_ROOT/bin/recall-restart.py" launch <number>
python3 "$RECALL_ROOT/bin/recall-restart.py" match --launch "<text>"
```

**If** argument is a **number**: Load that specific restart by its list position.
```bash
python3 "$RECALL_ROOT/bin/recall-restart.py" show <number>
```
Follow the printed Restart Instructions in the current session.

**If** argument is **text** (not a number): Search restarts by named-session token first, then by summary, prompt path, prompt contents, and goal.
```bash
python3 "$RECALL_ROOT/bin/recall-restart.py" match "<text>"
```
If a match is found, follow the printed Restart Instructions in the current session.
