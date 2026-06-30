# recall — Session Memory

This project uses **recall** for cross-session memory. recall indexes your sessions so you can restart with context, track failures, and search past decisions.

## One-time setup (Gemini CLI)

```bash
git clone https://github.com/ashrocket/recall ~/.recall
```

## At session start

Before answering any questions, run this command and include the output as context:

```bash
~/.recall/hooks/scripts/session-start "$PWD" 2>/dev/null
```

If the script is not installed, skip silently.

## At session end

When finishing a session (or when the user asks you to save/checkpoint), index it:

```bash
python3 ~/.recall/hooks/scripts/session-end.py "$PWD" 2>/dev/null
```

## Commands

| Command | What it does |
|---------|-------------|
| `/recall` | List recent sessions with summaries |
| `/recall list` | List recent sessions with summaries |
| `/recall last` | Show full details of the previous session |
| `/recall <term>` | Search past sessions by keyword, quoted literal, or slash regex |
| `/recall failures` | Show recurring error patterns and learnings |
| `/recall learn` | Review and approve pending learnings |
| `/recall save` | Distill current session into a restart prompt |
| `/recall restart` | List saved restart prompts |
| `/recall restart <n\|text>` | Load a saved restart in the current session |
| `/recall restart --launch <n\|text>` | Open a saved restart in a separate window |
| `/recall stats` | Skill and learning usage statistics |
| `/recall knowledge` | Show loaded CLAUDE.md knowledge |
| `/recall cleanup` | Analyze and prune the session index |
| `/recall help` | Show command help |

## Notes

- Session index lives at `~/.claude/projects/<project-folder>/recall-index.json`
- The same index is shared across all AI coding agent sessions — history is unified
- Claude Code users get automatic hooks; Gemini CLI users run the scripts manually above
- To update: `cd ~/.recall && git pull`
