# recall — Onboarding

The full walkthrough lives at **[recall.pages.dev/start.html](https://recall.pages.dev/start.html)** — a 3-minute speedrun (install → save → restart) plus a 4-minute tour of every `/recall` subcommand. Source: [`docs/start.html`](docs/start.html).

If you can't open the web page, here's the no-frills version.

---

## Install

**Claude Code (recommended):**
```
/plugin marketplace add ashrocket/recall
```
Allow always when prompted. Hooks (SessionStart, SessionEnd, PostToolUse:Bash) wire automatically.

**Codex CLI:**
```bash
git clone https://github.com/ashrocket/recall ~/.recall
```
Copy `AGENTS.md` from this repo into your project root (or append its contents). Codex
plugin installs use `.codex-plugin/plugin.json` and expose the bundled
`skills/recall/SKILL.md` dispatcher skill.

**Gemini CLI:**
```bash
git clone https://github.com/ashrocket/recall ~/.recall
```
Copy `GEMINI.md` from this repo into your project root.

---

## The 3-minute speedrun

1. `/recall` — verify (you'll see an empty session list; that's correct).
2. Do anything in your project, then `/recall save` — locally extracts the session into a restart prompt.
3. Close the session.
4. Open a fresh session, run `/recall restart 1` — the new session knows what you were doing.

That's the killer feature. Once it works, you've got it.

---

## Every subcommand, once

Run each of these one time so the surface area stops feeling unfamiliar. Skip any whose precondition isn't met yet — no harm.

| Command | When to use it |
|---|---|
| `/recall` | List recent sessions |
| `/recall list` | List recent sessions explicitly |
| `/recall last` | Full detail of the previous session |
| `/recall <term>` | Search across all indexed sessions |
| `/recall '.p8'` | Literal search for a token or filename fragment |
| `/recall /.*\.p8/` | Regex search |
| `/recall restart` | List saved restart prompts |
| `/recall restart <n\|text>` | Load a saved restart into the current session |
| `/recall restart --launch <n\|text>` | Open a saved restart in a separate window |
| `/recall knowledge` | Show the CLAUDE.md Claude has loaded |
| `/recall stats` | Skill and learning usage rollup |
| `/recall failures` | Failure patterns + inline SOPs |
| `/recall learn` | Approve/reject auto-proposed learnings |
| `/recall cleanup` | Dry-run prune analysis (use `--all` to execute) |
| `/recall help` | Show command help |

**Manufacture a failure for `/recall failures`:**
```bash
cat /tmp/recall-demo-nope
# cat: /tmp/recall-demo-nope: No such file or directory
```
Then `/recall failures` will have something to show.

`/recall learn` is usually empty on day one — learnings get auto-proposed after 3+ similar failures or a fail→success resolution pair.

---

## Shared state

All three platforms write to the same index:

```
~/.claude/projects/<project-slug>/
├─ recall-index.json    # searchable session index
├─ recall-restarts/     # saved restart prompts
└─ *.jsonl              # raw session files
```

Save in Claude Code, restart in Codex. Save in Codex, restart in Gemini. Same briefing, different agent.

---

## Troubleshooting

- **Hooks not firing (Claude Code):** check `/config` → hooks lists recall; restart Claude Code after install.
- **"No sessions yet":** sessions index at SessionEnd — close and reopen to trigger; confirm `~/.claude/projects/<proj>/recall-index.json` exists.
- **Codex/Gemini: script not found:** `ls ~/.recall/hooks/scripts/` to confirm path; re-clone if missing.
- **Wipe and start over:** `/recall cleanup --all` prunes noise without nuking restarts; restart prompts live in `recall-restarts/` — delete by hand.
