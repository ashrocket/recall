# recall — Improvement Opportunity Analysis

*2026-06-09. Grounded in (a) a deep-research sweep of Claude Code releases 2.1.128→2.1.169 and the Claude platform since 2026-02-01, (b) a read of the current codebase, and (c) empirical tests run on this machine. Confidence and provenance are marked per item.*

---

## 0. TL;DR — where the opportunity actually is

Stock Claude Code (as of v2.1.169) **does not** natively provide any of recall's three differentiators, so the niche is safe:

- **No storage-native or semantic search of long session history.** Native search = the `Ctrl+R` history picker (v2.1.129) and ephemeral agents-list text/URL filtering (v2.1.161). Cross-device searchable history is an open feature request (GH #47926, #41945). *(high confidence)*
- **No token-efficient one-shot save/restore distinct from `--resume`.** *(high)*
- **No Apple Intelligence / on-device model integration.** *(high)*

The platform helps at the **API/design layer**, and Anthropic's own memory-tool guidance *validates* recall's local-file design. The biggest concrete wins are:

1. **Storage-native search** — move the index to SQLite + FTS5 (and optionally `sqlite-vec` hybrid) so "tell me about when we worked on X" is a sub-second indexed query, not a linear scan. *Key-free, local.*
2. **On-device / cheap-LLM summarization** — use Apple Foundation Models (Swift helper now; `fm` CLI on macOS 27) and/or Haiku 4.5 for the save-digest and learning-triage work that currently has no cheap path. *Key-free or 5× cheaper.*
3. **Stop paying the LLM tax for display** — today's hard-won lesson (below): `/recall` listing should never round-trip the model.

---

## 1. The architectural truth we proved today (drives everything below)

We empirically established (4 prompt strategies × 2 models, plus the authoritative CC docs):

- **A `/recall` skill invocation *always* costs a model turn, and the model *always* re-renders the script output** into tables/menus/analysis. No prompt instruction suppresses this. Claude Code has **no** "output-only" command, the bash tool result is collapsed by a hardcoded UI rule, and `Stop`/`MessageDisplay` hooks cannot suppress the turn.
- One Opus `/recall` measured at **742 output tokens, ~$0.19**. That is the per-call "LLM tax" for what is a 0.26s local read.

**Design principle this implies:** *keep all retrieval, ranking, and formatting in local scripts; reserve the model only for when the user wants the agent to **act** on results.* This is the same lesson Anthropic states for the memory tool ("don't load everything into context; pull back only what's relevant"). It motivates the `!recall` fast path already landed on `main` and shapes the recommendations below.

---

## 2. Opportunity map (by your themes)

### Theme A — Token-efficient save/restore (the core "killer feature")

**What the platform now blesses** *(high)*:
- The **memory tool** (`memory_20250818`) is client-side, file-based, persists across conversations, needs no extra API keys — *the same shape recall already has.*
- Its **multi-session recovery pattern** is a near-exact description of `save`/`restart`: an initializer writes a progress log + checklist; later sessions read it to "recover full project state in seconds"; each session updates the log before ending.
- **Server-side compaction** (`compact-2026-01-12`, beta, ~150k-token trigger) + **context editing** (84% token cut in a 100-turn eval, Anthropic self-reported) form the platform's token-efficient save/restore — *conceptually what `/recall save` does locally with TF-IDF.*

**Opportunities:**
- **A1. Adopt the progress-log framing explicitly.** `save` already writes a one-shot restart prompt; add an append-only, structured **progress log per project** (decisions, open threads, "next") that `restart` reads and every `save` updates. This is the documented pattern and makes "tell me about when we worked on X" answerable from one rolling artifact, not N session digests. *Effort: M. Key-free.*
- **A2. Tighten the restart prompt toward the 1–2k-token "distilled summary" target** the sub-agent guidance cites. Measure restart-prompt sizes; cap and rank. *Effort: S.*
- **A3. (Stretch) Mirror the compaction-boundary idea**: when a live session nears its limit, `save` is the recall analog of "persist across the compaction boundary." Document this as the recommended workflow. *Effort: S (docs).*

### Theme B — Cross-device / cross-agent searchable history ("the super-useful part")

Today the index is a **per-project JSON blob** scanned with in-process TF-IDF (`lib/text_rank.py`). That's fine for one project but doesn't scale to "long history across many devices and agents," and there's no indexed query.

**The key-free, storage-native answer** *(high, but external + pre-1.0)*:
- **SQLite + FTS5** for keyword search and **`sqlite-vec`** (pure C, no deps, "runs anywhere SQLite runs") for KNN vector search, fused with **reciprocal rank fusion** into one hybrid query inside a single `.sqlite` file — *no services, no keys.* Embeddings via **`sqlite-lembed`** (Snowflake Arctic Embed 1.5 GGUF) locally, **or** Apple Foundation Models on Apple Silicon.

**Opportunities:**
- **B1. Migrate the session index to SQLite + FTS5.** Immediate win: true indexed full-text search across *all* projects/agents/devices, sub-second, ranking via BM25. The "search algorithm inherently defined in the storage mechanism" you asked for. Keeps the dependency-free spirit (SQLite ships with Python's `sqlite3`). *Effort: M–L. The highest-leverage structural change.*
- **B2. Add `sqlite-vec` hybrid search as an opt-in layer** for semantic "when did we work on the auth thing" recall where keywords miss. Embeddings generated on-device (Theme C) so still key-free. *Effort: L. Gate behind a flag; FTS5 alone already covers most of the value.*
- **B3. Cross-device unification.** The sync engine (`lib/sync_*.py`, Git/Cloud providers) already moves `session_metadata`; with a single SQLite store, syncing/merging one DB file (or per-device DBs UNION-queried) gives a genuine cross-device searchable history. *Effort: M, on top of B1.*

> Caveat: `sqlite-vec`/`sqlite-lembed` are pre-1.0. FTS5 is rock-solid and built in. **Recommend B1 now, B2 later.**

### Theme C — Apple Intelligence + cheaper LLMs (key-free / 5× cheaper work)

**Verified on this machine (macOS 26.5):** `FoundationModels.framework` ✅ and Swift 6.3.1 ✅ present; **`fm` CLI absent** (it's macOS 27); FM model assets/enablement *unconfirmed*. So:

- **C1. Ship a tiny Swift helper binary** (`bin/recall-summarize-apple` or similar) that calls Foundation Models' ~3B on-device model for: save-digest generation, the `recall-save-eval` A/B candidate (currently an LLM call), and learning-triage. **$0/call, private, no key.** Falls back to the existing path when Apple Intelligence is unavailable. *Effort: M. Highest "fits all constraints" item.*
- **C2. macOS 27 upgrade path:** swap the Swift helper's guts for the `fm` CLI (`fm respond`, `--schema` for structured JSON digests) when available — simpler, no compile. *Effort: S, later.*
- **C3. Haiku 4.5 for the cheap-cloud path** where on-device is unavailable: 5× cheaper than Opus 4.8, 3× cheaper than Sonnet 4.6. Use for digest/triage/rerank. Pair with **prompt caching** (0.1× cache reads) for the stable system/instruction prefix. *Effort: S–M.*
- **C4. The pending-learnings backlog** (21 in your Codex screenshot) is the natural first customer for C1/C3: auto-triage candidates with a cheap/free model so the user only confirms, instead of being the bottleneck.

### Theme D — Token efficiency of the plugin itself

- **D1. `!recall` fast path — DONE, on `main`, verified.** `recall`/`recall <term>`/`recall list` now default to `$PWD`. Binary measured at **0.26s**; the `!` shell mode is **doc-confirmed model-free** ("Run shell commands directly without going through Claude… does not require Claude to interpret or approve" — code.claude.com/docs/en/interactive-mode). This is the single biggest token saving for day-to-day "remind me" usage.
- **D2. ~~`/recall` → Haiku~~ — TESTED, DOES NOT WORK, removed.** The `model:` SKILL.md frontmatter never routed in this setup: 6 tests including per-message `stream-json` model inspection and direct namespaced invocation — every assistant message ran on the session model; Haiku never engaged. (Docs claim the field exists; empirically a no-op for this plugin skill as of CC 2.1.170.) Reverted; `!recall` covers the fast path instead.
- **D3. Audit the SessionStart banner cost.** It injects "N sessions / M pending learnings / K recurring issues" every session start — a fixed token cost on every session across every project. Confirm it pays for itself; consider making the detail lazy.
- **D4. Prompt caching** for any LLM the plugin does call (digest/triage): keep a stable prefix to get 0.1× reads.

### Theme E — Nested subagents (≤3 levels)

> Open question: the research found **no verified primary source** on a Claude Code nested-subagent depth cap (a claim asserting their absence was *refuted*, so nesting likely exists but the cap is undocumented). Treat "3 levels" as *your* design ceiling, not a platform fact.

Where recall could use bounded nesting (and the **dynamic Workflow** primitive, v2.1.154+, which "holds intermediate results in script variables so the orchestrator's context holds only the final answer" and can route stages to cheaper models):
- **E1. A `save` pipeline as a 2–3 level workflow:** L1 orchestrator → L2 parallel extractors (commands, failures, paths, topics) → L3 a single cheap-model summarizer. Intermediate extraction never enters the user's context; only the final restart prompt does. Maps cleanly onto C1/C3. *Effort: M.*
- **E2. Keep it ≤2 levels for search.** Search is local (Theme B) — no subagents needed. Reserve nesting for the generative `save`/`triage` paths only.

---

## 3. Prioritized recommendation

| # | Item | Fits constraints | Effort | Priority |
|---|------|------------------|--------|----------|
| D1 | `!recall` model-free fast path | ✅ done | — | **Shipped** |
| B1 | Session index → SQLite + FTS5 | key-free, storage-native search | M–L | **P0** |
| C1 | Swift Foundation-Models helper for digests/triage | on-device, $0, no key | M | **P0** |
| A1 | Explicit rolling progress-log for save/restart | key-free; matches Anthropic pattern | M | **P1** |
| C3/C4 | Haiku + caching for triage; auto-triage pending learnings | 5× cheaper | S–M | **P1** |
| D2 | Verify/keep `/recall`→Haiku | cheaper | S | **P1 (needs your test)** |
| B2/B3 | `sqlite-vec` hybrid + cross-device DB sync | key-free | L | **P2** |
| E1 | `save` as a ≤3-level workflow | token-efficient orchestration | M | **P2** |
| C2 | Move to `fm` CLI on macOS 27 | simpler on-device | S | **Later** |

**If you do two things:** **B1** (SQLite/FTS5 — the searchable-history backbone) and **C1** (on-device Swift summarizer — the key-free cheap-LLM engine). Together they deliver the cross-device search and the token-efficient, key-free save you described, and everything else layers on top.

---

## 4. Caveats & open questions (carried from research)

- **Betas / pre-1.0:** compaction (`compact-2026-01-12`) is beta; the 84% figure is Anthropic self-reported; `sqlite-vec`/`sqlite-lembed` are pre-1.0.
- **Platform gating:** Apple Foundation Models needs macOS 26+ on Apple Silicon **and Apple Intelligence enabled / model assets present** (unconfirmed on this machine — verify before building C1). The `fm` CLI is macOS 27.
- **Changelog is fast-moving** (scan was 2.1.128→2.1.169); negative findings ("no native X") can change any release.
- ~~**Not researched:** a feature-by-feature comparison of Mem0 / Letta-MemGPT / Zep / ChatGPT memory~~ → **Done; see §5.**
- **Unverified:** real-world quality/latency of Haiku 4.5 vs. the Apple 3B model for session-ranking and restore-prompt generation.

### Primary sources
- Claude Code changelog / CHANGELOG.md (feature scan)
- anthropic.com/news/context-management; platform.claude.com memory-tool, compaction, pricing docs
- code.claude.com/docs/workflows (dynamic workflows)
- github.com/asg017/sqlite-vec; alexgarcia.xyz sqlite-vec hybrid-search
- machinelearning.apple.com Apple Foundation Models 2025 updates; developer.apple.com/documentation/FoundationModels

---

## 5. Competitive comparison — memory agent systems (researched 2026-06-09)

*Four parallel research agents on primary sources (docs.mem0.ai, docs.letta.com, help.getzep.com/github.com/getzep/graphiti, developers.openai.com/codex + OpenAI announcements). Focused on recall's two core values: episodic "when did we work on X" recall, and token-efficient one-shot save/restore.*

### Feature matrix (the two things that matter)

| System | "When did we work on X" (episodic, temporal) | Token-efficient save/restore | Local-first / key-free | Write-path LLM cost |
|---|---|---|---|---|
| **Mem0** (OSS v3, Apache-2.0) | Partial — atomic facts + `created_at` filters; explicitly *not* episodic narrative; you reconstruct | **None** (closest: PreCompact hook stores summary-as-memories) | OSS yes (Qdrant local + SQLite); CC plugin needs *hosted* key | LLM call on every `add` |
| **Letta** (ex-MemGPT, Apache-2.0) | Partial — `/search` across agents' messages; temporal filters on semantic archival search; needs Postgres+pgvector server | **None** — resume = full agent-state reload; `.af` export is full state, not compact | Server infra heavy; local models possible | Embeddings per archival write; compaction summarizer |
| **Zep/Graphiti** (Apache-2.0 engine, hosted product) | **Best-in-class temporal**: bi-temporal graph (`valid_at`/`invalid_at`), point-in-time queries; but per-fact granularity loses session narrative | **None** — context blocks are fact-recall, not session resumption | Ingestion needs capable LLM (small local models break schemas); query path LLM-free | LLM + embedder per ingest |
| **ChatGPT memory** (consumer) | Since 2026-01: PersonalContextAgentTool searches full account history w/ citations (Plus/Pro, cloud-only, no API); Dreaming V3 self-revising memory | N/A (not a session tool) | No — cloud, account-locked | Hidden/server-side |
| **Codex CLI** | No — SessionPicker browse/filter only; native memories are *semantic* (conventions/preferences), not episodic | `/compact` summary is **ephemeral**; resume = **full transcript replay** | Yes (local JSONL + SQLite metadata DB) | Background, idle-gated |
| **recall** | **Yes — the core feature** (local ranked search over indexed sessions, cross-agent) | **Yes — the core feature** (persisted one-shot restart prompt) | **Yes** (TF-IDF write path = $0) | **Zero required** |

**Positioning takeaway:** nobody else occupies the intersection. Every system has *either* memory-as-facts (Mem0/Zep/ChatGPT — encyclopedic, the thing we explicitly don't want to be) *or* heavyweight full-state resume (Letta agent state, Codex transcript replay). The persisted *compact restart artifact* and local-first *episodic* search are genuinely differentiated. The closest convergent move is Codex's nascent rollout-search (v0.136 "compressed rollout search snippets" — watch this).

### Steal list (validated against our roadmap)

1. **SQLite index over JSONL + zstd cold compression** (Codex does exactly this) — independent validation of **B1**; Codex also proves the pattern at scale.
2. **Bi-temporal stamps + invalidate-don't-delete** (Zep): record *when it happened* separately from *when recorded*; supersede decisions instead of deleting ("switched from X to Y on date Z") — directly improves "when did we…" answers and learning lifecycle.
3. **Idle-gated background extract→consolidate with secret redaction pre-disk and rate-limit awareness** (Codex native memories) — a model for when/where to run our cheap-LLM triage (C1/C4) without interfering with active work. We already have secret scanning in sync; extend it to extraction time.
4. **Three-signal hybrid search with graceful dependency fallback** (Mem0 v3: BM25 + semantic + entity-match, falls back cleanly) — the shape B2 should take.
5. **Git-backed memory files with commit-message history** (Letta MemFS) — validates our existing git-sync design; their always-loaded `system/` dir vs lazy file-tree split mirrors our SessionStart-banner vs on-demand-detail question (D3).
6. **~1.6k-token context-block budget** (Zep's published average) — concrete target for **A2**'s restart-prompt cap.
7. **Citations back to source sessions** (ChatGPT's PersonalContextAgentTool) — `/recall` results should link the session detail file (already on disk) so the user can jump to provenance.
8. **`/compact <focus>` argument** (Codex) — let `/recall save <focus>` bias the restart prompt toward a named thread of work.

### Their gaps we exploit (the moat, stated plainly)
- Codex resume replays whole transcripts; its compaction summary is thrown away — **our restart prompt is the persisted, reusable version of the thing they discard.**
- Mem0/Zep answer "what is true," not "what were we doing" — fact stores, no session narrative.
- ChatGPT's history search is cloud-only, subscription-gated, no API, coarse timestamps.
- Nobody has a cross-**agent** (Claude+Codex+Gemini), cross-device, local-first story; that's ours today.
