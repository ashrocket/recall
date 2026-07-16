# /recall learn — Review Pending Learnings

Review and approve proposed learnings that recall captured from session failure patterns.

## Step 1: Run the script

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
exec "$RECALL_ROOT/bin/recall" "$PWD" learn $ARGUMENTS
```

`$ARGUMENTS` is everything after `learn` (e.g., `--batch`, `--approve 1`, `--reject 2`).

## Step 2: Display results

Show the full output.

## Step 3: If pending learnings were shown, offer next actions

- Ask the user which ones to approve or reject by index number
- Run again with `--approve <N>` or `--reject <N>` as needed
- If they want to approve everything, suggest `--batch`

Active learnings surface in `/recall failures` and are injected into future sessions via the SessionStart hook.
