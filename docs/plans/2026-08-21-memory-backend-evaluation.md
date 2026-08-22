# Memory-backend evaluation for agentic-coding project memory

> Decision memo. Produced 2026-08-21 from a five-lane research pass (local-first, edge/serverless, managed cloud, agent-memory frameworks, and what coding tools already do), each lane grounded in 2026 sources and checked against recall's own code. Informs the v3 index spec.

---

# Decision Memo: Which vector/memory backend to connect to recall — and how

**To:** recall maintainer
**From:** Design lead
**Re:** Semantic-search / memory-store backend for agentic coding memory
**Bottom line:** Don't connect a vector database. Ship the FTS5/BM25 spine your own v3 spec already specifies as the *entire* answer for now, and treat semantic search as an optional, local, single-file assist you add later only if a measured miss-rate demands it. The one place I'd amend your v3 plan: when that assist arrives, make it a `BLOB` column + numpy cosine in `recall.db`, not `sqlite-vec + fastembed`.

---

## 1. The honest verdict: keyword+recency is the engine, semantic is at most a thin assist

**A vector layer is not worth it as a default. Hybrid — BM25 + recency/importance as the backbone, with an opt-in thin semantic assist — is the right answer, and even the assist is a "prove it first" feature.**

The reasoning is not "vectors are bad." It's that coding memory is dominated by exact-identifier lookup — filenames, symbols, error strings, flags, config keys — which is precisely where BM25/regex wins and where semantic similarity adds nothing. The evidence I'd stake the call on is *vendor behavior*, not benchmark claims:

- **Anthropic removed the embedding/vector-DB pipeline from Claude Code (May 2025)**; grep "outperformed everything by a lot."
- **Sourcegraph Cody retired embeddings** for keyword + code-graph.
- **Cursor uses vectors for *code chunks* but not for its *memories*** — the durable-memory layer is short auto-injected text, not a vector problem.
- **GitHub's Blackbird code-search engine chose ngram/exact-match**, not vectors.

Four independent teams walking back from embeddings for code context is stronger than any single benchmark — and it converges exactly on recall's shape. (Two dossier claims I deliberately did *not* rely on: the "GitHub chose BM25 over vectors" line traces to a dead podcast, and Lane 3's "2026 benchmarks show BM25 leads on correctness" carries no citation. The vendor-behavior argument is sturdier and doesn't need them.)

Two facts about recall specifically seal it:

1. **Scale makes the vector value proposition irrelevant.** Your corpus is dozens–hundreds of small docs, tens of KB, biggest index ~52KB. Every throughput/ANN argument for a vector DB is noise at this size.
2. **recall's moat is curation + review gate + cross-machine sync, not retrieval cleverness.** You already have the high-signal half of the memory-store split (distilled, reviewed docs via pending-learnings + `autoMemoryEnabled`) that competitors like claude-mem lack. Spending complexity budget on a vector DB spends it on the wrong axis.

The honest minority case *for* a semantic assist: purely conceptual queries that share no tokens with the stored doc ("how did we handle auth retries" when the doc says "backoff on 429"). That is a real but minority slice, and it is worth serving **only if it costs almost nothing** — which rules out every managed DB and every LLM-extraction framework, and rules *in* exactly one thing: a few hundred float vectors sitting inside the SQLite file you're already building.

---

## 2. Ranked recommendation

### Connect these

| Rank | Backend | One-line reason |
|---|---|---|
| **1** | **SQLite FTS5/BM25 in `recall.db`** (your v3 Tier 1, as specced) | Zero new dependency (stdlib `sqlite3`), per-project single file, wins the exact-identifier majority, already your decision. This is the whole v1. |
| **2 (opt-in, later)** | **In-file `BLOB` vectors + numpy cosine, embedded with model2vec** — *amending* your Tier-2 `sqlite-vec + fastembed` plan | Co-locates vectors in the same `recall.db` with **no compiled extension, no `enable_load_extension` probe, no 0.x pin, no platform wheels**. RRF-fuse with BM25. |

**On the Tier-2 amendment:** your v3 spec picks `sqlite-vec + fastembed`. At a few hundred vectors, sqlite-vec's entire value (DiskANN/IVF ANN) is the same irrelevant-at-this-scale noise we just dismissed; it costs you a pre-1.0 compiled loadable extension whose `enable_load_extension` support system CPython sometimes disables. A `vec BLOB` column beside `sessions_fts` + numpy cosine is sub-millisecond over hundreds of rows and deletes that entire dependency/dealbreaker surface. And `fastembed` pulls **onnxruntime**; **model2vec** is numpy-only static — strictly lighter and fully offline. Keep sqlite-vec named as the upgrade *if* a project ever crosses ~10k vectors (it won't — that's your v3 trigger, below).

### Do NOT adopt

- **Any managed cloud vector DB (Pinecone, Qdrant Cloud, Weaviate, Vertex, MongoDB Atlas, managed pgvector)** — puts the network in the query path (kills offline), none ride your Worker, all egress sensitive repo context off-box.
- **Vertex AI Vector Search** — worst fit in the field: always-on node floor (~$68–800/mo), no scale-to-zero, GCP lock-in, for a few hundred markdown docs.
- **Supabase / Neon / Qdrant free tiers** — idle-death traps: Supabase pauses after 7 days, Qdrant Cloud auto-*deletes* after 4 weeks idle, Neon cold-starts — i.e. your project is asleep or gone exactly when you return to an old repo.
- **LanceDB / Chroma / tantivy** — directory + versioned-manifest stores that a file-by-file blob sync can land inconsistently → *corrupt*, not merely stale.
- **DuckDB VSS** — index persistence is flagged experimental; docs warn of data loss/corruption on unclean shutdown. Unacceptable for durable memory.
- **Mem0 / Zep / Memobase / Cognee** — mandatory LLM-extraction-on-every-save + a Postgres/Neo4j/Redis tier; reshapes clean markdown into a lock-in graph; benchmarked on conversational personalization (LoCoMo/LongMemEval), not coding.
- **Letta** — a rival stateful-agent runtime, not an embeddable backend; adopting it means recall becomes a Letta plugin and surrenders its file model.
- **Anthropic Managed Agents memory stores** — not locally reachable from the CLI, workspace-scoped to Anthropic's platform. Its value is *confirmation* that "small text docs on a filesystem" is right — validation, not a backend.

---

## 3. Recommended architecture

**Index shape.** Exactly your v3 spec: one `recall.db` (SQLite, WAL) per project under `~/.claude/projects/{project_folder}/`, holding the `sessions` table + `sessions_fts` FTS5 virtual table (BM25, porter/unicode61), with the 180-day recency decay + `importance`/`evergreen` scoring you already designed. The optional semantic arm is one more table in the *same file*:

```
CREATE TABLE session_vec (
  session_id     TEXT PRIMARY KEY REFERENCES sessions(id),
  content_sha256 TEXT NOT NULL,      -- cache key + staleness guard
  dim            INTEGER NOT NULL,
  vec            BLOB NOT NULL        -- int8 or float32, model2vec output
);
```

Query = BM25 rank list ⊕ cosine rank list fused via **RRF**, with `importance`/`evergreen`/recency as the existing boosters. This is the "200-line hybrid in one SQLite file" pattern, minus any extension.

**Embeddings run LOCALLY, never in the Worker.** Offline is a near-hard constraint for recall; a Worker embedding call puts the network in the *write* path and egresses doc text. Embed on the client at distill/save time — the save is already a deliberate, gated event (`pending-learnings` + `autoMemoryEnabled`), which is the perfect embed hook. Cloudflare Workers AI BGE (on the account you already run, 10k free Neurons/day) is the *fallback* only, kept behind an explicit opt-in for users who want it; it is never the default.

**How it rides the sync / D1 — the key architectural call: don't sync the vectors at all.** Vectors are a pure derived projection of text that already syncs. So:
- Sync the markdown/session text through your existing `/v1/files/{rel}` push-pull with `content_sha256` optimistic concurrency (`If-Match` / `If-None-Match`) exactly as `lib/sync_cloud.py` does today.
- **Exclude the vector data from sync** (via `.recallignore`) and **rebuild it locally** from synced text on next index build. This dissolves the binary-LWW-conflict worry for the vector layer entirely and keeps per-machine embedding costs invisible to the sync protocol. (Note the wrinkle in your own spec: beyond `keep_count`, `recall.db` becomes the *sole* record because sidecars are probabilistically deleted — so "derived, don't sync" applies cleanly to the *vector table*, which is always re-derivable, not necessarily to the whole DB. Scope the exclusion to the vectors, or re-embed from the retained `failures_json`/summary text.)
- **Never put vectors in D1** (2 MB/row cap, per-row read accounting). If a Worker-side semantic option is ever built (v3), it's *one R2 object per project* (a matrix), never D1 rows.

**Per-project isolation** is free: one `recall.db` per project folder means vectors are physically partitioned per project with zero cross-project leakage — the multi-tenancy problem that Vectorize/Upstash solve with "namespaces," recall solves with the filesystem.

**Offline behavior:** index build, BM25, model2vec embedding, and numpy cosine all run locally with zero network. Sync is optional and moves only text. An offline machine rebuilds its own vectors from synced text; search never touches the network. This is the single property no managed option can match.

**Embedding-model choice + cost/privacy:** **model2vec static** (potion-class, ~8–30 MB, numpy-only, CPU, offline). Cost: one-time ~30 MB download, then effectively $0 recurring. Privacy: nothing leaves the machine — decisive, because the corpus is sensitive repo context. **Caveat (see Risk 2):** static-embedding quality on code/identifier tokens is unverified; pilot before shipping.

---

## 4. Tiered rollout

**v1 — ships in a week, NO vectors.**
The `recall.db` FTS5/BM25 Tier-1 spine from your v3 spec, fused with the existing `text_rank.py` recency/`importance`/`evergreen` signals; keep the regex/quoted-literal exact-match arm. Cheap, no-dependency borrows worth folding in now: (a) target the **AGENTS.md** convention so any agent auto-loads your durable docs (you already have `AGENTS.md`); (b) keep the **approve-before-save gate** (you have it); (c) **name/heading-address** doc sections (Serena's principle) so links survive reflow; (d) add an **in-link count** signal to ranking — MEMORY.md is already a link graph, so "how many docs point here" is Aider's PageRank idea applied to a graph you already have, ranking above recency alone. This captures the overwhelming majority of the value. Ship it.
→ **Trigger to v2:** *measured* evidence conceptual queries are failing. Instrument v1 search to log "keyword returned nothing but a relevant memory existed." Build v2 on that miss-rate, not on speculation. You already have the save-eval + usertesting-feedback harnesses to generate the eval set.

**v2 — thin semantic assist, opt-in, off by default.**
Add the `session_vec` `BLOB` table in the same `recall.db` + model2vec local embeddings, embed-on-save, RRF-fused. Gate behind a config flag mirroring `autoMemoryEnabled`. Vectors excluded from sync, rebuilt locally. **Do not ship until the two v2 gates in Risks 1–2 are cleared.**
→ **Trigger to v3:** a project's vector count routinely exceeds ~10k (linear cosine starts to bite), **or** a team/shared-index feature demands server-side semantic search.

**v3 — only if warranted (expected outcome: never ships).**
If and only if scale/team demands exceed the local single-file model: an *optional* Worker-side semantic layer on the account you already run — brute-force cosine over **one R2 object per project** (still not a vector DB), embedded via Workers AI BGE, with FTS5 as the offline fallback. Promote to Cloudflare Vectorize only if per-project vectors blow past the R2-cosine comfort zone (tens of thousands). Never default; always an online add-on.

---

## 5. What to refuse, and why

**Managed cloud vector DBs (Pinecone, Qdrant, Weaviate, Vertex, Atlas, managed pgvector).** All three of recall's non-negotiables break at once: network in the query path (no offline), a second service that doesn't ride your Worker (new egress path for sensitive repo context), and an external embedding pipeline the user must call and pay for. The free tiers are worse than the paid ones for *your* usage pattern — Supabase pauses (7 days), Qdrant deletes (4 weeks), Neon cold-starts — because intermittent per-repo memory is exactly the access pattern those policies punish. Each solves a scale/convenience problem recall does not have.

**Agent memory frameworks (Mem0, Zep/Graphiti, Memobase, Cognee, Letta).** Built and benchmarked for *conversational-agent personalization* — their suites (LoCoMo, LongMemEval, BEAM) don't even contain exact-identifier retrieval, which is recall's dominant query. All (except Anthropic's file tool) impose an LLM extraction/entity-graph pipeline on every save plus a DB tier (Postgres/pgvector+Neo4j, Redis), violating zero-ops/local-first/no-embedding-pipeline and reshaping clean path-addressed markdown into a lock-in-prone graph. Letta is a competing agent runtime, not a component. **Steal two ideas, adopt none:** Cognee's embedded-local-stack as proof local-first is achievable, and Memobase's capped-3-LLM-call distillation as a cheap session-compression pattern.

**Directory/manifest local stores (LanceDB, Chroma, tantivy) and DuckDB VSS.** Even though "local," they're the wrong *shape*: directory-with-versioned-manifest stores that your file-by-file blob sync can land inconsistently (corrupt, not stale), or — DuckDB VSS — persistence its own docs flag as experimental and crash-unsafe. sqlite-vec was the only vector store that survived the sync constraint, and we just showed a `BLOB` column beats even that at recall's scale.

The through-line: each refused option trades a constraint recall *cannot* give up (offline, zero-ops, single-file sync, no embedding pipeline, no data egress) for a capability recall does not need (ANN at scale, managed multi-tenancy, conversational personalization, knowledge graphs).

---

## 6. Risks / open questions (ranked)

1. **Vectors leak past your redaction model — a fail-*unsafe* security gap (v2 gate, do not ship without handling).** `worker/src/memory/secrets.ts` exists precisely because "a key written once leaks repeatedly" — memories replay verbatim into later sessions. But your redaction surface (`worker/src/memory/versions.ts`: `redacted_at`, `redactVersion()`, content nulled when `redacted_at` set) operates on *text*. A vector is a non-null projection of the same content sitting in a side table that `redactVersion()` would not touch — and you cannot grep a float array to confirm a secret is gone. **Mitigations, all required before v2 ships:** embed only *post-scrub* text (`scrub_for_index()` already exists); key the vector to `content_sha256` so a redaction (new version → new hash) invalidates the stale vector; and make redaction/secret-rejection also drop the vector row. This ties the vector arm to the immutable-version model you just built — get it wrong and a secret that slips the 8-pattern scan leaks in embedding space, un-auditable.

2. **Static-embedding quality on code/identifier text is unverified — the entire v2 premise (v2 go/no-go gate).** model2vec's published gains are general-purpose prose; distillation trades accuracy, and code tokens (symbols, flags, stack traces) may embed poorly. If quality is bad, v2 shouldn't exist. **Mitigation:** pilot on a real recall query set with your save-eval / usertesting harness and gate on *measured* lift over BM25-alone. Fallback if it underperforms: local onnx MiniLM (Continue.dev proves it runs offline) at the cost of onnxruntime — or ship no vectors. This risk fails *safe* (bad → don't ship), which is why it ranks below #1.

3. **Do you even have the miss-rate signal to justify v2?** The v2 trigger is a measured conceptual-query miss-rate; if v1 search doesn't log "keyword found nothing but the memory existed," that signal doesn't exist and v2 becomes a guess. **Mitigation:** instrument v1 search from day one.

4. **numpy becomes a (light) new dependency for a currently stdlib-only tool.** The vector arm needs numpy (model2vec pulls it anyway). Low risk: it's opt-in, so stdlib-only users are unaffected, and numpy is far lighter than the compiled-extension/onnxruntime path we rejected. Feature-detect and degrade to FTS5-only if absent.

5. **Binary `recall.db` under last-write-wins sync, plus the sole-record-beyond-`keep_count` wrinkle.** Predates vectors and is unchanged by this proposal (your JSON index already has LWW semantics — a wash). The vector-layer exclusion from sync sidesteps it for the new code. Open question you already own: is blob-LWW acceptable for old-session records the DB is now the *only* copy of, or do you want per-record merge? Watch for corruption on concurrent two-machine writes.

6. **RRF / recency / importance / in-link fusion weighting.** Corpus-dependent and not obvious. Lowest risk — tunable and reversible — but needs a small eval loop to set defaults before v2 default-on.