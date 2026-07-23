# /recall user-testing feedback

- **Tester:** Claude Code agent (model `claude-fable-5`, effort high, claude-code CLI)
- **Session:** `0ffd1a02-240a-4ac9-9b6a-611ae6e4d8f1`, project `-Users-ashrocket-ashcode-recall` (the recall repo itself)
- **Date:** 2026-07-22 (evening, EDT; transcript timestamps below are local)
- **Recall version:** 3.4.1
- **Flow exercised:** forensic replay of the last 30 minutes of recall usage across four sessions, from the repo side — session-start hook, save→eval→promote artifacts, both restart consumption paths, and the eval trend log. This report deliberately does not repeat the findings in `usertesting-feedback.claude-fable-5-high-7d6ce2c6-….md` (the in-flow tester); it adds what is only visible from outside the flow.

## Vantage point

This session started cold in `~/ashcode/recall` and was asked to gather "everything learned about /recall in the last 30 minutes." Nothing about those 30 minutes was in my context — everything below was reconstructed from the artifacts recall and its sessions left behind: transcripts under `~/.claude/projects/`, the restart registry, `recall-save-evals.jsonl`, and the first feedback report.

## Timeline of the 30 minutes (reconstructed)

| Time | Session | Event |
|---|---|---|
| 19:46 | `7d6ce2c6` (figma, project) | `recall save figma-palette-muted-text` writes the local extractor prompt `figma-use-find-css-design.prompt` |
| 19:48 | `7d6ce2c6` | `recall-save-eval.py log --winner llm` appends to `recall-save-evals.jsonl`; registry pointer promoted to the LLM prompt |
| 19:55 | `7d6ce2c6` | post-promotion edits to `figma-use-find-css-design.llm.prompt` (regeneration grep recipes + non-Claude-agents section) |
| 19:55 | `b485f3ee` (project) | fresh session restarts the checkpoint **in-session** via the `/recall` alias; agent correctly restates the ratified decisions and the one blocking question |
| 19:56 | `bb0d8f2d` (project) | `restart --launch` window opens with the promoted LLM prompt as its first message; runs one git-status/worktree check |
| 19:59 | `7d6ce2c6` | writes the first user-testing feedback report into this repo |
| 20:00 | `b485f3ee` | Ashley: "YES" → agent resumes the backlog in a fresh `palette-lockdown` worktree, exactly per the prompt's worktree instruction |

## What worked well (visible only from outside)

1. **The restart round-trip demonstrably closed.** The promoted LLM prompt cold-started two independent sessions within a minute. The in-session one (`b485f3ee`) reproduced the palette decisions, honored the "work in a worktree, not the shared checkout" instruction without being reminded, and asked exactly the ratified-vs-blocking question the prompt flagged (`hover/status colors — ask, don't assume`). That is the product working as designed, verified from the consumer side.
2. **The artifacts are self-auditing.** Everything I needed to reconstruct the half hour existed on disk with timestamps and sha256s: the registry keeps both prompt generations, the eval log records the judge's reason, and post-promotion edits flow through because the registry stores a path, not a copy. Recall's paper trail made this report possible.
3. **The feedback convention bootstrapped itself.** The figma agent located this checkout (`ls -d ~/ashcode/recall`), wrote its report, and its filename became the schema this report and the new command follow.

## Friction and findings, in severity order

1. **Recall cannot answer the very prompt that produced this report.** "What did you learn about /recall in the last 30 minutes" is unanswerable *by recall*: indexing runs at SessionEnd (this repo's session-start hook reported "14 sessions indexed; last 5d ago" while four recall-touching sessions were live), and search is scoped per project (the activity was in `-Users-ashrocket-project-code-project`, invisible from this repo). I had to bypass recall and read raw transcripts sorted by mtime. Suggestions: a `recall live` mode that indexes still-open transcripts on demand, and an `--all-projects` search flag.
2. **The local extractor is 0-for-5 in its own eval log.** Every entry in `recall-save-evals.jsonl` since 2026-06-28 is `winner=llm`, and the judge's reason is the same each time: the extractor captures git state and activity but no decisions ("the extractor has only git state", "captured no decisions", "led with a terminal spinner as its top key signal"). This is now trend data, not anecdote. Suggestions: surface extractor win-rate in `recall stats`; treat a sustained 0% as the signal to either make LLM distillation the default save path or to build the decision-line extractor ("decided / let's go with / merge it") the 7d6ce2c6 report proposed.
3. **Double-restart collision, no guard.** The same checkpoint was consumed twice within ~60 seconds — the `restart --launch` window (`bb0d8f2d`) and the in-session restart (`b485f3ee`). The launched window did one command and was abandoned; two agents briefly held the same "resume the backlog" mandate against one shared checkout. Suggestion: record consumption metadata on restart (session id + timestamp) and have a second consumption within a short window print "this checkpoint was restarted N min ago by session X — continue anyway?".
4. **Restart names still don't match prompt filenames.** Confirmed from outside: the checkpoint saved as `figma-palette-muted-text` lives on disk as `figma-use-find-css-design[.llm].prompt` (slug from the session title). Cross-referencing registry ↔ eval log ↔ filesystem required matching sha256s from the eval JSONL. Same fix as the 7d6ce2c6 report's item 5: derive the filename from the given name.

## Appendix A — original user-testing prompt (Ashley, this session, verbatim)

> Take everything you've learned about /recall in the last 30 minutes and put it into unique including our original and modified prompts. in the ~/ashcode/recall directory with a usertesting-feedback.model-config-session-id.md should be the format of the filename. - this should be an additional but better written prompt embedded in one of our plugin commands. it will only work if you have the repo checkout and if the agent doesn't know where the repo is it will need to search for and remember it.

## Appendix B — the rewritten prompt

Codified as the new plugin command `commands/usertesting-feedback.md` (→ `/recall:usertesting-feedback`) in this repo. It makes explicit what the original left implicit: locate the repo checkout (never the plugin cache), verify it by the `ashrocket/recall` git remote, search and then *remember* the path if unknown, derive `<model>-<config>-<session-id>` for the filename, structure the report, and include the prompt pairs verbatim from the registry files. The command file is the canonical copy; it is not duplicated here.

## Appendix C — original local extractor prompt (verbatim, `recall-restarts/figma-use-find-css-design.prompt`, sha256 `efd15388…`)

Note: this is the authoritative registry copy — the version quoted in the 7d6ce2c6 report has shell commands truncated by terminal width.

```markdown
# [figma-use] WHere in this repo can I find — Session Context

## Generated By
`recall-save.py` using local parsing and extractive TF-IDF ranking. No LLM distillation was used.

## Working Directory
`/Users/ashrocket/project/code/project`

## Branch
`dev` (3 changed path(s))

## Session Focus
[figma-use] WHere in this repo can I find the css / design system ? | The only colors we should have should come from figma, and f

## Key Signals
- vitating… (14m 46s · ↓ 33.6k tokens) Tip: Run /install-github-app to tag @claude right from your Github issues and PRs ❯ THis is not actual completed> this was prototype [Image #1] so it's not good
- Ok go ahead and merge the PR and then let's write a restart prompt using recall and the local llm
- So the design's answer to "what color is muted text" is ≈#XXXXXX/#XXXXXX - in this statement, the design is our current code/ or figma?
- text-gray-500 shojul dbe something else, find what that element is in the figma ? yeah ?
- just put the screenshots for the examples in a document proving the case for muted text and XXXXXX/XXXXXX

## Local Keywords
project, users, ashrocket, grep, text-muted-token, project-worktrees, src, design

## Files And Paths
- `/Users/ashrocket/project/code/project/ios/Project/Core/Design/ProjectDesign.swift`
- `/Users/ashrocket/project/code/project-worktrees/text-muted-token/src/index.css`
- `~/.ai-context/screenshots.md`

## Git Status
- `D node_modules`
- `?? .claude/`
- `?? prompt.txt`

## Recent Commits
- `[COMMIT_SHA_1] Merge pull request #144 from project-org/design/pulse-feedback-phase-figma`
- `[COMMIT_SHA_2] Merge pull request #152 from project-org/chore/reland-docs-test-consolidation`
- `[COMMIT_SHA_3] test: consolidate e2e suite under test/ + add NewCo demo recording suite`
- `[COMMIT_SHA_4] chore: ignore local agent/tool state, generated test artifacts, and Figma captures`
- `[COMMIT_SHA_5] docs: add product audit and supporting designs`

## Recent Commands
- `cd "/private/tmp/claude-501/-Users-ashrocket-project-code-project/7d6ce2c6-ad0f-4d7f-b096-72b5369b997a/scratchpad" && python3 - <<'EOF' import bas`
- `tail -80 ~/.ai-context/screenshots.md`
- `cd "/private/tmp/claude-501/-Users-ashrocket-project-code-project/7d6ce2c6-ad0f-4d7f-b096-72b5369b997a/scratchpad" && python3 - <<'EOF' import bas`
- `S="/private/tmp/claude-501/-Users-ashrocket-project-code-project/7d6ce2c6-ad0f-4d7f-b096-72b5369b997a/scratchpad" /usr/bin/curl -sL -o "$S/real-ca`
- `cd "/private/tmp/claude-501/-Users-ashrocket-project-code-project/7d6ce2c6-ad0f-4d7f-b096-72b5369b997a/scratchpad" && python3 - <<'EOF' import bas`
- `cd /Users/ashrocket/project/code/project-worktrees/text-muted-token && npm run build 2>&1 | tail -2 && git add -A && git commit -q -m "design: tex`
- `cd /Users/ashrocket/project/code/project-worktrees/text-muted-token && gh pr edit [N] --body "## What The Style Guide v3.1 palette (the Colors se`
- `cd /Users/ashrocket/project/code/project-worktrees/text-muted-token && gh pr checks [N] 2>&1 | head -8; gh pr view [N] --json mergeable,mergeState`
- `cd /Users/ashrocket/project/code/project-worktrees/text-muted-token && gh pr merge [N] --merge 2>&1 | tail -2 && git fetch origin dev -q && git lo`
- `RECALL_ROOT=${CLAUDE_PLUGIN_ROOT:-} if [ -z "$RECALL_ROOT" ]; then for base in "$HOME/.claude/plugins/cache/recall/recall" "$HOME/.codex/plugins/cac`

## Failures Or Risks
- None captured.

## Restart Instructions
1. `cd /Users/ashrocket/project/code/project`
2. Inspect `git status --short` and the files listed below.
3. Continue from the session focus and key signals; verify behavior before reporting completion.
4. Use the recent commands as evidence, not as a script to replay blindly.

## Source
- Session ID: `7d6ce2c6-ad0f-4d7f-b096-72b5369b997a`
- Prompt generated from structured recall data and current git state.
```

## Appendix D — modified/promoted LLM prompt (verbatim, `recall-restarts/figma-use-find-css-design.llm.prompt`, incl. 19:55 post-promotion edits)

````markdown
# Restart: Project palette enforcement (figma session, 2026-07-22)

## Generated By
LLM distillation (Fable 5, session 7d6ce2c6) — compared against the local extractive prompt via recall-save-eval.

## Where you are
`/Users/ashrocket/project/code/project`, branch `dev`. The shared checkout is dirty with other sessions' state — do feature work in a worktree off `origin/dev`, PRs base `dev`, no Claude attribution in commits. Ashley's voice: curt, kind, briefly funny.

## Decisions made this session (do NOT re-open)
- **Canonical palette = the 11 swatches in Figma's Colors section, nothing else.** XXXXXX, XXXXXX, XXXXXX, XXXXXX / XXXXXX, XXXXXX, XXXXXX, XXXXXX, XXXXXX, XXXXXX / XXXXXX.
- **Muted/secondary text = solid `#XXXXXX`** — match the design lead's designs faithfully. Hierarchy by size/weight, not lighter ink. No 12th swatch, no alpha tricks.
- **On Figma page [REDACTED], everything right of the divider (x beyond a known threshold, "WIREFRAMES" label [REDACTED]) is wireframes; the Audience List stack is a prototype import.** Neither is design canon — never cite them as evidence. The numbered frames (03_wizard*, 21_profile*, 15_*, 01_dashboard*) are wireframes wherever they sit.

## Shipped
- **PR #[N] merged to dev ([COMMIT_SHA], auto-deploys):** `text-gray-500` (25×) + `text-muted-foreground` (29×) + raw `text-[#XXXXXX]` (6×) → `text-text-muted` = `#XXXXXX`, across 18 files; deleted `--color-muted-foreground`. Build clean, 702/702 tests.
- **Evidence brief artifact (v4, shareable):** [ARTIFACT_URL_REDACTED] — palette screenshot, real-frame receipts with Figma layer links, census, PR link.

## Key references
- Figma: file `[FIGMA_FILE_ID]` (Project-MVP-v2), working page `[REDACTED]`, Colors section `[REDACTED]`. On Claude: Figma MCP + figma-use skill; `get_metadata` page listing is broken for this file (shows only Cover) — enumerate via `figma.root.children`. **Figma access is OPTIONAL for the remaining backlog — it's all code work; the palette hexes above are the complete spec.** (Artifact URL below needs Ashley's claude.ai login; non-Claude agents can skip it.)
- Design tokens: `src/index.css` `@theme` block (Tailwind v4, no tailwind.config). iOS mirror: `ios/Project/Core/Design/ProjectDesign.swift`.
- Tailwind v4 gotcha: it scans docs/*.md and even CSS comments for class-name candidates — a class name in prose generates a live utility.

## Remaining work (the actual backlog, in order)
1. **Palette lockdown in `src/index.css`:** `--color-*: initial` at top of `@theme`, define only the 11 + ratified semantic tokens; remap the legacy oklch tokens (`foreground`, `brand`, `border`, `surface*`, `destructive` — ~170 usages via text-foreground/bg-brand/border-border etc.) onto palette hexes; drop unratified `#XXXXXX`/`#XXXXXX`; fix 2× `#XXXXXX` in tour-popover CSS.
2. **Component sweep:** 616 Tailwind default-palette class usages across 51 files (worst offenders: six components each with 30+ usages) + ~324 raw off-palette hexes (~45 files, concentrated in a handful of wizard/dashboard-style components).
3. **`worker/lib/email.ts`:** 27 off-palette hexes (emails keep inline hexes — just palette ones).
4. **iOS `ProjectDesign.swift`:** 7 off-palette values incl. `0xXXXXXX` (Tailwind gray-200) + `0xXXXXXX`/`0xXXXXXX`.
5. **CI guard:** ~10-line script greping for default-palette classes + non-palette hexes (lockdown alone doesn't fail builds — unknown utilities are silently skipped).

## Blocking decision before step 1-2 can finish
The palette defines no hover/pressed states and no success/error/warning colors (~200 of the violations are semantic status UI). Candidate mapping floated but NOT ratified: XXXXXX=warning/in-progress, XXXXXX=success, XXXXXX=error (index.css comment already says navy=errors), XXXXXX=hover. Needs Ashley's or the design lead's sign-off — ask, don't assume.

## Regenerate the violation lists (run from repo root)
```sh
# Tailwind default-palette classes in components:
grep -roE '(text|bg|border|ring|fill|stroke|from|to|divide|outline)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-[0-9]+' src --include='*.tsx' | cut -d: -f1 | sort | uniq -c | sort -rn
# Off-palette raw hexes (palette = the 11 canon colors):
PALETTE='<redacted-project-palette>'
grep -roE '#[0-9a-fA-F]{6}\b' src worker --include='*.tsx' --include='*.ts' --include='*.css' | awk -F: '{print $1":"tolower($2)}' | grep -vE ":#($PALETTE)$" | cut -d: -f1 | sort | uniq -c | sort -rn
```

## Verify
`npm run build` + `npm test` (root config; worker tests use `npm run test:worker`, separate config). Check compiled CSS in `dist/assets/index-*.css` for stray default-palette utilities.

## Non-Claude agents (Codex etc.)
Everything you need is in this file — no CLAUDE.md, MCP, or memory-dir access assumed. Repo facts that normally live in CLAUDE.md: two Vitest configs (never run worker tests with the root config); `dev` branch auto-deploys on push; demo/prod deploy only via a separate manual CI trigger; PRs always base `dev`.
````
