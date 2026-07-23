File a user-testing feedback report on recall itself, written from whatever you just experienced using it.

Run this after exercising any recall flow (`save`, `restart`, `restart --launch`, search, `failures`, the `recall-save-eval.py` local-vs-LLM comparison). These reports are the raw material recall's development runs on: record what actually happened in this session, not generic impressions.

This command only works on a machine with the recall *source repo* checked out — reports go in the repo root, not the plugin cache.

## 1. Locate the recall repo checkout

The plugin cache under `~/.claude/plugins/cache/recall/…` is NOT the repo. You need the git checkout.

1. If you already know the path — from memory, an earlier report, or because you are working inside it — use it.
2. Otherwise search, cheapest first:
```bash
for d in "$HOME/ashcode/recall" "$PWD"; do
  [ -f "$d/.claude-plugin/plugin.json" ] && grep -q '"name": "recall"' "$d/.claude-plugin/plugin.json" \
    && [ -d "$d/.git" ] && echo "FOUND $d" && break
done
# Fallback: search home for checkouts, excluding plugin caches
find "$HOME" -maxdepth 4 -type f -path '*/.claude-plugin/plugin.json' -not -path '*/plugins/cache/*' 2>/dev/null \
  | xargs grep -l '"name": "recall"' 2>/dev/null | sed 's|/\.claude-plugin/plugin\.json||'
```
3. Verify before writing anything: `git -C "$dir" remote get-url origin` should point at `ashrocket/recall`.
4. **Remember what you found.** If you have persistent memory (Claude Code auto-memory, project notes you may edit), record the checkout path so the next session skips the search. If you have none, state the path prominently inside your report — future agents grep existing reports to find it.
5. If no checkout exists on this machine, stop and tell the user. Do not write into the plugin cache and do not clone the repo unasked.

## 2. Name the file

`usertesting-feedback.<model>-<config>-<session-id>.md`, at the repo root.

- `<model>` — the exact model id you are running as (e.g. `claude-fable-5`, `gpt-5.2-codex`).
- `<config>` — the setting that most distinguishes this run: reasoning effort (`high`, `medium`), `fast`, or `default` if nothing stands out.
- `<session-id>` — your session UUID (Claude Code: the transcript filename under `~/.claude/projects/<project>/`, also visible in your scratchpad path). If you cannot determine one, use `unknown-<YYYYMMDD-HHMM>`.

One report per session. If the file already exists, update it in place rather than creating a variant.

## 3. Write the report

Structure (match the tone of the existing `usertesting-feedback.*.md` files in the repo root):

- **Header** — tester (model, config, harness), session id + project, date, recall version (from `recall help` or the plugin cache `plugin.json`), and the flow exercised.
- **What happened** — a short narrative of the actual run.
- **What worked well** — concrete behaviors worth keeping, each tied to something that happened.
- **Friction and bugs, in severity order** — every item must be reproducible from this session: quote the command, the output, or the file it came from, and suggest a fix when you have one. No generic feedback.
- **Appendices — original and modified prompts, verbatim.** If the session touched the save/eval flow, include the local extractor prompt (`recall-restarts/<name>.prompt`) and the LLM/promoted prompt (`<name>.llm.prompt`) exactly as generated, plus any post-promotion edits. Copy from the registry files, not from your context — these pairs are the primary evidence for improving the extractor; never paraphrase them.

## 4. Afterwards

Leave the file uncommitted unless the user asks you to commit or push. Mention the report path in your summary so the user can read it.
