# From Prompts to Protocols

## A narrative history of our agentic coding practice

**Evidence snapshot:** 2026-08-08

**Primary archive window:** 2026-05-06 through 2026-08-01

## Executive thesis

Our practice began as high-agency improvisation: give an agent a large outcome, point it at the browser, shell, cloud account, or live product, and keep pushing until something worked. It was unusually ambitious from the start. We were already using worktrees, browser automation, subagents, live deployment, and restart notes in May. But these techniques were mostly ingredients inside individual prompts. The agent was powerful; the operating system around it was thin.

Over the next three months, the center of gravity moved out of the prompt and into durable controls:

- work moved into isolated branches and worktrees;
- brainstorming, planning, execution, review, and branch closure became distinct stages;
- plans, architecture notes, `CLAUDE.md`/`AGENTS.md`, Pidgin documents, and Recall checkpoints carried state between sessions;
- stop hooks and autonomous loops turned persistence into a managed mechanism;
- tests, PRs, CI, browser checks, and deployment probes became completion gates;
- subagents changed from general-purpose critics into bounded workers and auditors;
- “done” evolved from “the agent made a change” to separate claims about implementation, merge, deployment, and live behavior.

The shortest description is: **we moved from heroic prompts to an engineering control plane.**

## What was examined

This history uses every primary `recall-index.json` found under `~/.claude/projects/` at the snapshot date:

| Coverage | Count |
| --- | ---: |
| Project-directory indexes | 54 |
| Indexed sessions | 368 |
| Indexed sessions with a matching detail sidecar | 368 (100%) |
| Earliest indexed session | 2026-05-06 |
| Latest indexed session | 2026-08-01 |
| Sessions explicitly carrying a `codex-` ID | 4 |

“Project-directory index” is deliberate wording. Repositories moved between directories, and some conceptual projects therefore have multiple indexes. Backup copies such as `recall-index.json.bak.*` were excluded to avoid double-counting.

The main index supplies the complete session-level counts. Detail sidecars preserve representative messages, commands, failure categories, and skill use, but the writer caps them at 30 user messages, 50 commands, and 20 failures. The quantitative analysis therefore uses index counts; sidecars are used for qualitative evidence. Failure counts are Recall heuristics, so an intentional non-zero diagnostic command can be classified as a failure. The direction of the trend is more meaningful than any single count.

The archives also contain command bodies and historically included sensitive material. This narrative intentionally excludes credentials, tokens, personal message content, and raw command text.

## The quantitative shape of the change

| Period | Sessions | Commands | Recorded failures | Failures per 100 commands | Skills recorded | Active indexes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| May 6–31 | 125 | 5,462 | 706 | 12.9 | 116 | 23 |
| June | 66 | 3,043 | 264 | 8.7 | 140 | 14 |
| July 1–August 1 | 177 | 8,207 | 610 | 7.4 | 194 | 29 |

Commands per session stayed roughly flat—43.7 in May, 46.1 in June, and 46.4 in the final period—while recorded failure density fell about 42%. We did not improve by asking agents to do less. We kept the same operational intensity while adding enough structure to reduce wasted motion.

The skill record shows what that structure was made of. Recall-related invocations dominate, followed by `superpowers:brainstorming`, Pidgin, writing plans, artifact design, subagent-driven development, finishing branches, and worktrees. The names are noisy because Recall itself was renamed from `agent-recall:recall` to `recall` and then `recall:recall`; that naming churn is itself evidence of consolidation from a collection of commands into one remembered workflow.

## Prologue: memory began as error correction

The design record predates the live archive. The January 2025 concept was not “remember the whole project.” It was a shell-failure skill: observe a failed command, recognize a later fix, and ask whether the pair should become a global or project SOP. The original unit of memory was a mistake and its repair.[D01]

By January 2026, the diagnosis had widened. The Recall v2 design explicitly said that session indexes existed but “wisdom dies with each session”: learnings were empty, knowledge was not surfaced at session start, cross-project search was missing, and agents repeated solved debugging work. The proposed answer combined session search, project knowledge, pending learnings, and failure SOPs.[D02]

That progression foreshadows the later practice:

1. First remember commands.
2. Then remember fixes.
3. Then remember project facts and handoffs.
4. Finally, encode how the agent should work and what evidence completion requires.

## Phase I — May 6–14: maximum agency, minimum ceremony

The first archived sessions are expansive, direct, and operational. A May 6 Career session asked the agent to turn a job-search tool into a conversational onboarding product for a beta user. In one session it worked across a worktree, application code, email delivery, cloud data, deployment, and live health checks, then ended by asking for a recap/restart prompt. The index records 23 user messages, 79 commands, and 12 failures.[A01]

That pattern repeats across very different projects:

- On May 7, a Retailaer session used a subagent to call Codex and “ruthlessly test” the live site: 65 commands and 15 failures.[A02]
- On May 8, a Career session drove a long Greenhouse/browser application workflow: 249 commands and 48 recorded failures.[A03]
- Game, iOS, blog, analytics, mail, RFP, and cloud sessions moved rapidly between code, browser, deployment, and product decisions.

The characteristic unit of work was a **mission**. Prompts often combined discovery, implementation, deployment, and evaluation. Agents were expected to infer the intermediate plan and keep going. Browser state was treated as part of the workspace. Live systems were not a final destination after local verification; they were often where the work happened.

Subagents were already present, but their role was usually broad: ask Codex or Gemini to critique the work, have two agents act as players, or assemble a panel of reviewers. This was “more intelligence on the task,” not yet a stable decomposition protocol.

There were early signs of the future. Worktrees appear in the very first session. Recall and restart prompts were used within days. Brainstorming and writing-plan skills were available. But those controls were optional tactics, invoked inside a high-energy session rather than forming the default lifecycle around every change.

The cost is visible in the 12.9 failures per 100 commands. Some of that count is heuristic noise, but the detailed records show real path errors, command-shape errors, Git problems, missing tools, browser uncertainty, and live-service friction. Secret handling was also too casual: commands sometimes read or piped local credential material directly, and the archive retained command bodies. Later security fixes and metadata-only queue design are a direct answer to this era’s assumptions.

## Phase II — May 15–June 8: autonomy acquires structure

Around mid-May, the practice begins to separate concerns.

A May 15 Career session explicitly required a unique worktree and combined worktree setup, brainstorming, and Pidgin delivery.[A04] Five days later, the Eagle Zero project asked for a collaboration and handoff system for developers in Estonia and Hungary; the session used brainstorming, writing-plans, and subagent-driven-development skills.[A05] The question was no longer only “can the agent build this?” It was becoming “how can people and agents exchange work without collisions or lost context?”

By June 3, Retailaer asked for a complete Playwright regression suite in a separate worktree using Claude agents. The session added systematic debugging to brainstorming and exercised CI, branch behavior, and regression gates.[A06] Similar sessions increasingly mention:

- separate worktrees and branch closure;
- regression suites and content validation;
- PR creation, approval, merge, and branch reconciliation;
- architecture summaries and review artifacts;
- Pidgin as a durable handoff surface rather than a transient notification;
- explicit plans before implementation.

The skills start forming a pipeline: brainstorm, write a plan, execute it, request or synthesize review, finish the branch. June records 140 skill invocations across only 66 sessions, compared with 116 across 125 sessions in May. Some are duplicate Recall tags, but the qualitative shift is unmistakable: named procedures are replacing one-off instructions.

Subagents change too. Instead of merely offering extra opinions, they begin to receive bounded roles: build a test suite, research one option, review a particular surface, or execute a section of a plan. Coordination files and artifacts make their output inspectable by the next worker.

This phase does not reduce ambition. It makes ambition composable.

## Phase III — June 9–July 8: sessions become resumable operations

June introduces persistence as an explicit operating mode. A June 9 Looki session combined Recall, code review, test-driven development, Cloudflare tooling, a PR, and an “autonomous loop” timer; it recorded only one failure across 63 indexed commands.[A07] Autonomous loop checks also appear in Pidgin and Retailaer work. Stop hooks carry a session-scoped condition and continue nudging the agent until the condition is satisfied.

The crucial change is that state increasingly lives outside conversational memory:

- plans are saved under `docs/` and passed to execution skills;
- `coord.md`, architecture documents, and Pidgin HTML describe the current state to humans and other agents;
- repository guidance becomes shared context across related projects;
- Recall gets named restart prompts rather than anonymous timestamps;
- checkpoints identify the working directory, goal, current state, and next action.

On June 25, Recall itself was asked to use a named Claude or Codex session as the restart name.[A08] On June 29, a CarerCare checkpoint explicitly recorded that it had been generated by local parsing and extractive TF-IDF rather than LLM distillation.[A09] On July 4, a BandMusicGames checkpoint opened with a working directory and a `Goal` section.[A10] On July 6, a MusicLoops session invoked subagent-driven development against a specific plan file and used Recall to carry it forward.[A11]

This is more important than a better summary format. A checkpoint changes the unit of continuity from “the previous chat” to a durable work package. A new agent can inspect the repository and checkpoint, resume the plan, and be judged against the same goal. The work can survive context limits, process restarts, and tool changes.

Recall’s product evolution mirrors the practice it observed. The repository added named restart support on June 30, deletion and quality improvements on July 2, and later A/B evaluation of locally extracted versus LLM-distilled restart prompts. Memory became a tested product surface rather than a transcript dump.

## Phase IV — July 9–22: persistence meets gates

In early July, long-running work becomes more explicitly orchestrated. Archives contain `TaskCreate`, teammate messages, cheap loops, session-scoped stop conditions, and plan-file restarts. Agents can work while the user steps away, but they are increasingly bound to artifacts and checks.

The clearest turning point is July 17 in Retailaer OMS. A stop hook reported that `pnpm verify --affected` was red and stated, “You are not done.”[A12] This is a different philosophy from the May sessions. Completion is no longer whatever the agent says after making progress. The environment can reject the claim.

The same period shows more deliberate lifecycle work:

- lint and test failures are handled before merge;
- Terraform and architecture changes are reviewed for ignore coverage and sensitive material;
- PRs and branch merges are explicit operations;
- Pidgin artifacts carry architecture maps and review results;
- read-only and adversarial review sessions appear alongside implementation sessions;
- agents distinguish a missing dependency, an expired credential, a live propagation delay, and an actual code defect instead of treating every obstacle as an invitation to edit code.

This is where “autonomous” starts to mean **independent within constraints**, rather than merely “keep taking actions.”

## Phase V — July 23–August 1: evidence-first closure and the Codex pivot

The final archived week has the recognizable shape of the current practice. A UserHappy session resumed from an LLM-distilled, post-merge palette checkpoint.[A13] It was followed by narrowly scoped read-only QA audits against named branches and files. A Retailaer OMS session framed Terraform work in terms of verifying ignore coverage, scrubbing plan files, and picking up CI failures before commit.[A14] UserHappy design work compared implementation and Figma state. Eagle Zero’s August 1 session launched the OIDC site for direct exploration rather than treating deployment output alone as proof.[A15]

The quantitative record supports the qualitative shift. The final period contains more commands than May, across more active indexes, while failure density is 7.4 per 100 commands instead of 12.9. The agents are not less active. They are operating inside better-defined rails.

At the same time, the platform is changing. Only four sessions in the primary Recall indexes have a `codex-` session ID. Two are in May and two on July 6. The archive therefore records the beginning of the move to Codex, not its completion. The Recall repository makes the direction explicit a few weeks later: commits on July 26–27 made commands Codex-native, and the July 28 durable-indexing design addressed Codex’s short SessionEnd budget.[C01][D03]

That design is a compact statement of the mature engineering instinct: do not use a detached process and hope; enqueue a durable job naming the exact transcript, make writes idempotent and concurrency-safe, keep credentials out of queue files, and preserve an explicit recovery path. The memory subsystem itself has adopted the same principles as the coding practice—exact identity, bounded work, durable state, safe retries, and observable failure.

## The current Codex-first loop

The current effective Codex guidance completes the arc. The preferred workflow is now:

1. Define `Goal`, `Context`, `Constraints`, `Done when`, and `Verification required` when needed.
2. Plan the change.
3. Inspect the repository and relevant docs.
4. Make scoped edits.
5. Run focused checks and broader checks when risk is high.
6. Review the diff.
7. Verify behavior, including Browser QA for UI work.
8. Report behavior, files, and verification.

This loop is not bureaucracy added to agentic work. It is the mechanism that makes high agency trustworthy.

The post-archive Codex record shows how far this has gone. In an August 4 UserHappy release, the shared dirty checkout was preserved through an isolated worktree; acceptance items were mapped to code and tests; a focused fix passed unit and worker suites, build, migrations, deployment, and live probes; the exact merged and deployed SHA was tracked; and a fresh browser verified first paint. The final report separately identified implementation, merge, deployment, live verification, untouched environments, and the remaining unaudited authenticated flow.[E01]

That is the strongest contrast with May. In May, the agent was asked to make the world change. By August, it was also required to prove exactly which world changed, from which commit, through which gate, without disturbing adjacent work.

## What changed, in one view

| Early tendency | Mature tendency |
| --- | --- |
| One large mission prompt | Goal plus explicit context, constraints, done condition, and evidence |
| Plan inferred inside the session | Plan stored as an inspectable artifact |
| Work in whichever checkout is open | Preserve dirty work; isolate scoped changes in branches/worktrees |
| Subagents as general critics | Bounded agents with named tasks and reviewable outputs |
| Browser and production as the workspace | Local/focused verification first; live environment as a separate gate |
| Continue until the agent feels done | Stop hooks, tests, CI, and browser checks can reject completion |
| Restart notes as emergency recap | Named, structured, tested checkpoints used proactively |
| Chat contains the state | Repo docs, guidance, artifacts, indexes, and rollout summaries contain the state |
| Deployment implies success | Implemented, merged, deployed, and live-verified are separate states |
| Credentials treated as convenient inputs | Presence checks, redaction, scrubbed artifacts, and metadata-only durable queues |
| Load a broad source and search through it | Project the smallest useful keys, join lightweight indexes, and touch payloads only when required |
| Agent as clever executor | Codex as the engineering control plane |

## What remained constant

The story is not a reversal. Several instincts were present from the beginning and remain strengths:

- **Outcome orientation.** The work was always tied to real products, users, and operational results.
- **Tool fluency.** Shell, browser, cloud consoles, Git, deployment systems, mobile builds, and external services were treated as one workspace.
- **Willingness to delegate.** Multi-agent critique and parallel exploration appeared immediately.
- **Dogfooding.** Recall, Pidgin, Squawk, loop mechanisms, and workflow skills were improved through actual use.
- **Persistence.** Context limits were treated as an engineering problem to solve, not a reason to stop.

The change was learning where these strengths needed boundaries. We did not replace agency with caution. We made agency inspectable, resumable, and accountable.

## Lessons worth preserving

1. **Keep state outside chat.** A good checkpoint, plan, repo guide, or rollout summary is part of the implementation, not administrative residue.
2. **Use the smallest stable control that works.** A worktree prevents collisions; a focused test proves a behavior; a stop gate rejects a false finish; a browser check proves the visible result.
3. **Separate lifecycle claims.** Code can be implemented but unmerged, merged but undeployed, deployed but not live-verified.
4. **Let agents be ambitious inside a narrow ownership boundary.** High autonomy works best when scope, target environment, destructive actions, and completion evidence are explicit.
5. **Treat recurring prompts as product defects.** If the same procedure is repeatedly explained, move it into `AGENTS.md`, a skill, a hook, or a script.
6. **Inspect the exact current state.** Current SHA, live logs, browser behavior, dirty worktree, and actual configured tools outrank remembered assumptions.
7. **Design handoffs for a different agent.** If a fresh agent cannot tell what is true, what changed, what remains, and how to verify it, the handoff is incomplete.
8. **Never open a large data source by default.** Predict the memory, compute, I/O, and latency envelope before acting. Select only the identifiers and metadata needed for the decision; join lightweight indexes before loading payloads; stream or chunk unavoidable work with explicit bounds; and stop before an operation can crash, swap, or monopolize the machine. The cheapest safe read is often the read you avoid entirely.

## Evidence ledger

The paths below are local, sensitive session archives. They identify the supporting record without reproducing its raw command or message content. Each session can be resolved as `~/.claude/projects/<project-slug>/recall-sessions/<session-id>.json`.

| ID | Date | Project | Evidence used |
| --- | --- | --- | --- |
| A01 | 2026-05-06 | Career | First indexed product-onboarding mission; live services, worktree, restart recap; session `0fe0d72f-d7c9-40ec-9dba-a8448a8be375` |
| A02 | 2026-05-07 | Retailaer | Codex subagent used for aggressive live-site testing; session `00d38f0f-6b30-425a-8a2a-e71001e2c9d5` |
| A03 | 2026-05-08 | Career | Long browser-driven application run; session `8d1db98d-513a-444f-8948-38bca24d1b55` |
| A04 | 2026-05-15 | Career | Explicit unique worktree plus brainstorming and handoff; session `36218cba-1599-4a5b-8c89-bb95637de597` |
| A05 | 2026-05-20 | Eagle Zero | Human/agent collaboration and handoff design; session `0ee6e808-569c-4753-a246-e8b15f91ae24` |
| A06 | 2026-06-03 | Retailaer | Separate-worktree Playwright regression and agent review; session `ca2ab057-1f3c-497f-984e-d8bd245861d2` |
| A07 | 2026-06-09 | Looki | Autonomous loop, TDD, review, Cloudflare, and PR; session `a652a3c5-f798-419f-b204-3dd9556ec6fc` |
| A08 | 2026-06-25 | Recall | Named restart design; session `8d397e3e-f234-44ca-9260-9bb5357050c6` |
| A09 | 2026-06-29 | CarerCare | Locally extracted structured session checkpoint; session `0846584c-9d07-4f4c-9162-2a9a566fb547` |
| A10 | 2026-07-04 | BandMusicGames | Checkpoint with working directory and explicit goal; session `0ca115d8-f8e9-471a-833e-b7afc08dac38` |
| A11 | 2026-07-06 | MusicLoops | Plan-file-driven subagent development and Recall resume; session `f40ff19e-febb-4841-88f1-d31806f871cc` |
| A12 | 2026-07-17 | Retailaer OMS | Stop gate rejected completion while verification was red; session `324649f9-f418-4b7a-b0fa-5898a2b6632c` |
| A13 | 2026-07-23 | UserHappy | LLM-distilled post-merge restart followed by scoped audits; session `b8bf1644-e5ae-4642-9aba-26c4b37582ee` |
| A14 | 2026-07-26 | Retailaer OMS | CI, ignore coverage, scrubbing, and commit readiness; session `2999b9c6-6f86-4603-a03e-7a4372cd2569` |
| A15 | 2026-08-01 | Eagle Zero | OIDC site launch and direct exploration; session `9c4c9798-7df9-4399-859f-7ef5e437a58a` |

Repository and post-archive evidence:

- **D01:** `docs/plans/2025-01-25-shell-failures-design.md`
- **D02:** `docs/plans/2026-01-27-recall-v2-design.md`
- **D03:** `docs/superpowers/specs/2026-07-28-durable-session-index-queue-design.md`
- **C01:** Recall commits `2373d8a`, `7be0c98`, `1e1afb7`, and `537b39b`, 2026-07-26 through 2026-07-28
- **E01:** Codex rollout `019fcde2-2ef6-7660-8d2b-edb8f54d77ef`, UserHappy Cortex feedback release and exact-SHA Dev verification

## Closing interpretation

The deepest change was not Claude to Codex, or one skill to another. It was a change in what we considered the product of an agent session.

At first, the product was the action: code written, form submitted, deployment attempted, site changed. Then the product became the change plus a recap. Then it became a durable work package with a plan and restart point. Finally, it became a verified state transition: scoped code, preserved surrounding work, an exact commit, passed gates, observed behavior, and a handoff another agent can trust.

That is the narrative of our agentic practice: **from getting an agent to do the work, to building a system in which agents can do consequential work safely and prove what they did.**
