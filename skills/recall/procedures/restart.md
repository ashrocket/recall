# /recall restart — Resume a Saved Session

`$ARGUMENTS` is everything after `restart` from the original `/recall restart [...]` invocation.

## Dispatch

By default, load restart prompts into the current session. Do not open separate Terminal/Claude windows unless `$ARGUMENTS` starts with `--launch` or `-l`.

**If** no argument or argument is **`list`**: List all saved restarts with their numbered position and named-session token.
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/recall-restart.py list
```

**If** argument starts with **`--launch`** or **`-l`**: Open a separate Terminal/Claude window for that restart.
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/recall-restart.py launch <number>
python3 ${CLAUDE_PLUGIN_ROOT}/bin/recall-restart.py match --launch "<text>"
```

**If** argument is a **number**: Load that specific restart by its list position.
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/recall-restart.py show <number>
```
Follow the printed Restart Instructions in the current session.

**If** argument is **text** (not a number): Search restarts by named-session token first, then by summary, prompt path, prompt contents, and goal.
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/recall-restart.py match "<text>"
```
If a match is found, follow the printed Restart Instructions in the current session.
