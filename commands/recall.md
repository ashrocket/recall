Search, save, and restart recall sessions for the current project.

Fast path: run the wrapper, which uses the compiled Rust reader when available and falls back to Python as needed.

```bash
${CLAUDE_PLUGIN_ROOT}/bin/recall "$PWD" $ARGUMENTS
```

Common forms:
- `/recall` — recent sessions
- `/recall list` — recent sessions
- `/recall <term>` — local ranked search
- `/recall /regex/` — regex search
- `/recall last` — previous session
- `/recall failures` — failure patterns and learnings
- `/recall save [name]` — checkpoint current work; names the restart (falls back to the Claude session title, then a summary slug)
- `/recall restart [list|summary|n|name|text]` — list or summarize saved named checkpoints, or load one in the current session
- `/recall restart --launch <n|name|text>` — open a checkpoint in a separate window as a fresh, named `claude` session
- `/recall restart delete <n|name|text>` — delete a saved restart and its stored prompt file
- `/recall resume [n]` — list or launch saved native `claude --resume` tokens (captured by cmux at save time)
- `/recall learn` — review pending learnings
- `/recall stats` — skill and learning usage stats
- `/recall knowledge` — show loaded CLAUDE.md knowledge
- `/recall cleanup` — analyze and prune the session index
- `/recall help` — full help
