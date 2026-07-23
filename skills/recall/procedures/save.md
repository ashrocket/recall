# /recall save — A/B Restart Checkpoint

`/recall save <name>` records `<name>` as the restart's name (shown in the prompt box, `/resume` picker, and terminal title when reopened with `--launch`). With no argument the name comes from the Claude session's title, then a summary slug.

For now, save runs both approaches so we can compare quality:

0. Resolve the install root once, the same way as every other recall route:
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
1. Run the local extractor and show its output. When the user supplied a name after `/recall save` (it arrives as `$ARGUMENTS`), forward it as `--name` so the restart and its `--launch` session are named:
   ```bash
   python3 "$RECALL_ROOT/bin/recall-save.py" "$PWD" --name "$ARGUMENTS"
   ```
   With no name, drop the flag:
   ```bash
   python3 "$RECALL_ROOT/bin/recall-save.py" "$PWD"
   ```
2. Extract the `Saved restart prompt: ...` path from that output. Call it `LOCAL_PROMPT`. When reporting the checkpoint back to the user, quote the `Name: ...` line verbatim — the filename slug is derived from the given/resolved name when one exists (falling back to the session summary only when neither an explicit name nor a session title is available), but treat it as a filesystem-safe abbreviation, not a substitute for the actual reported name.
3. Ask the helper for a sibling path for the LLM candidate:
   ```bash
   python3 "$RECALL_ROOT/bin/recall-save-eval.py" candidate --local-prompt "$LOCAL_PROMPT"
   ```
4. Write a second restart prompt at that returned path using LLM judgment. Keep it concise and follow the same structure as the local prompt: working directory, branch/current state, what mattered, open risks, and concrete restart steps.
5. Compare the local prompt and LLM prompt. Judge which is better for a fresh agent to resume from using: factual correctness, specificity, actionability, useful brevity, and omission risk.
6. Append the comparison log:
   ```bash
   python3 "$RECALL_ROOT/bin/recall-save-eval.py" log "$PWD" --local-prompt "$LOCAL_PROMPT" --llm-prompt "$LLM_PROMPT" --winner local|llm|tie --reason "<one sentence>"
   ```

The local extractor registers the initial restart entry. If the comparison winner is `llm`, the eval logger promotes the matching restart registry entry to the LLM prompt so `/recall restart` loads the better handoff.

## Quality Guidelines

Good restart prompts:
- include exact cwd, branch/git state, changed files, tests, and next actions
- preserve unresolved risks and blockers
- avoid transcript dumps and irrelevant retries
- stay compact enough to paste into a fresh session without wasting context
