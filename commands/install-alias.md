Install a personal `/recall` shortcut at `~/.claude/commands/recall.md` that dispatches to `/recall:recall`.

One-time, opt-in setup. After running, `/recall` works as a short alias for `/recall:recall`. The namespaced command stays available either way. To remove the alias later, delete `~/.claude/commands/recall.md`.

The alias lives in your personal commands directory, so it is independent of the plugin — uninstalling recall does not remove it.

## Procedure

1. Check current state:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/install-alias.py check
```

2. **If output starts with `MISSING`**: write the alias and report success.
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/install-alias.py write
```
Tell the user: `/recall is now available as a shortcut for /recall:recall.`

3. **If output starts with `EXISTS`**: show the user the current contents (everything after the `---` line) and ask whether they want to overwrite it.
   - If they decline: stop. Do not modify the file.
   - If they accept: run the same `write` command from step 2 and confirm.
