# recall cloud: "Git for Agent Sessions"

## Summary

A paid cloud service ($1.50/quarter) that provides versioned document storage for agent session data — restart prompts, learnings, SOPs, session metadata, ADM files, and agent config snapshots. Built on Cloudflare Workers + R2 with Stripe billing. Positions as "Git for Agent Sessions" — familiar push/pull/log semantics backed by R2 object versioning, not actual git.

The entire codebase is open source. Users can:
1. **Use our hosted service** — pay $1.50/quarter, paste an API key, done
2. **Self-host** — fork the repo, plug in their own Cloudflare + Stripe credentials, deploy
3. **Resell** — same as self-host, charge their own customers at their own price

## Relationship to git-backed sync

The existing git-backed sync spec (`2026-03-30-git-sync-adm-design.md`) defines a sync engine with provider adapters for GitHub, GitLab, and Bitbucket. The cloud service is a **new provider adapter** for that same sync engine.

```
/recall sync init --github      → user's GitHub repo (free, actual git)
/recall sync init --gitlab      → user's GitLab repo (free, actual git)
/recall sync init --bitbucket   → user's Bitbucket repo (free, actual git)
/recall sync init --cloud       → our managed R2 backend ($1.50/quarter)
```

Same YAML format. Same `.recallignore`. Same secret scanning. Same conflict-free design. The cloud adapter translates push/pull into HTTP REST calls instead of git operations.

## Goals

1. Provide a zero-setup sync backend — pay, paste key, push
2. Protect margins with multi-tier rate limiting (session/hour/day/week/month)
3. Ship as open source so anyone can self-host or resell
4. Keep the Worker dumb — auth, rate limits, storage, billing, nothing else
5. Never store credentials in code — all secrets via environment variables

## Non-goals

- Implementing actual git protocol (R2 object versioning is the VCS)
- Team/shared sync (single-user only for v1)
- Encryption at rest (v2)
- Server-side search (search happens in the sync engine, client-side)
- Real-time / continuous sync

---

## Architecture

```
┌─ Sync Engine (existing) ────────────────────────────────┐
│                                                          │
│  Provider adapters:                                      │
│  ├── git (GitHub, GitLab, Bitbucket) → git push/pull     │
│  └── cloud (NEW) → HTTP REST to Worker                   │
│                                                          │
└──────────────────────────────┬───────────────────────────┘
                               │ HTTPS
                               ▼
┌─ Cloudflare Worker: recall-cloud ─────────────────┐
│                                                          │
│  ┌─────────┐  ┌──────────┐  ┌────────────────────────┐  │
│  │  Auth   │→ │  Rate    │→ │  Route Handler         │  │
│  │(API key)│  │  Limiter │  │  PUT/GET/LIST/DELETE    │  │
│  │         │  │  (KV)    │  │                        │  │
│  └─────────┘  └──────────┘  └────────┬───────────────┘  │
│                                       │                  │
│  ┌─────────────────────┐              │                  │
│  │  Stripe Webhook     │              │                  │
│  │  /webhook/stripe    │              │                  │
│  └─────────────────────┘              │                  │
│                                       ▼                  │
│  ┌─────────────┐    ┌─────────────────────────────────┐  │
│  │  KV Store   │    │  R2 Bucket (versioning enabled) │  │
│  │             │    │                                 │  │
│  │ • api keys  │    │  /{user_id}/                    │  │
│  │   (hashed)  │    │    ├── restarts/*.yaml          │  │
│  │ • rate      │    │    ├── learnings/*.yaml          │  │
│  │   counters  │    │    ├── adm/*.yaml                │  │
│  │ • usage     │    │    ├── sops/*.yaml               │  │
│  │ • tier info │    │    ├── sessions/*.yaml           │  │
│  │             │    │    └── agent-configs/*.yaml      │  │
│  └─────────────┘    └─────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### Why Cloudflare, not AWS

| | Cloudflare Worker + R2 | AWS ECS Fargate + S3 |
|---|---|---|
| Baseline (zero traffic) | $0 | ~$23/mo (container + ALB) |
| Egress | $0 | $0.09/GB |
| Profitable from user # | 1 | ~200 |
| Deploy | `wrangler deploy` | Container + ALB + IAM + ECR |

### R2 object versioning as the VCS

No git server. No commits. No refs. R2's built-in object versioning provides:
- Automatic version history on every write
- Restore any previous version
- List all versions of any file
- Soft delete with version retention

Each file is a complete, self-contained YAML document. No diffs, no deltas, no changelogs. Push a file, it's stored as-is. Push again, old version is retained automatically.

---

## API

The Worker exposes a minimal REST API. The sync engine's cloud adapter is the primary client.

```
PUT    /v1/files/{path}              Store a file (R2 auto-versions)
GET    /v1/files/{path}              Get latest version
GET    /v1/files/{path}?version={n}  Get specific version
GET    /v1/files/{path}/versions     List all versions of a file
GET    /v1/files/?after={timestamp}  List files changed since timestamp
DELETE /v1/files/{path}              Soft delete (versions retained)
DELETE /v1/files/{path}/versions      Trim old versions (keep=N param)
GET    /v1/status                    Storage used, rate limits, billing
GET    /v1/export                    Signed R2 URL for full data download
POST   /v1/auth/rotate               Rotate API key
POST   /v1/webhook/stripe            Stripe billing events
```

All endpoints except `/v1/webhook/stripe` require `Authorization: Bearer {api_key}`.

### What the user types vs. what happens

| Local command | Cloud call | What happens |
|---|---|---|
| `/recall sync push` | `PUT /v1/files/*` for each changed file | Upload changed files since last push |
| `/recall sync pull` | `GET /v1/files/?after={ts}` then `GET` each | Download files changed since last pull |
| `/recall sync status` | `GET /v1/status` | Show storage, limits, billing |
| `/recall cloud export` | `GET /v1/export` | Download everything as tarball |

### Push/pull protocol

**Push (fast-forward only):**
1. Sync engine gathers files changed since last push timestamp
2. Secret scan runs locally (existing engine feature)
3. `.recallignore` filtering runs locally
4. For each file: `PUT /v1/files/{path}` with file content as body
5. Worker stores in R2, R2 auto-versions, returns new timestamp
6. Sync engine records new push timestamp locally

**Pull:**
1. `GET /v1/files/?after={last_pull_timestamp}` returns list of changed file paths
2. For each path: `GET /v1/files/{path}` downloads latest content
3. Sync engine writes files to local recall directories
4. Sync engine regenerates local index
5. Records new pull timestamp locally

No merge. No conflict resolution. Two machines creating different files produce different paths (unique by timestamp + ID). If the same file was modified on two machines, latest write wins — versions are retained so nothing is lost.

---

## Storage tiers

User-configurable, same categories as the git-backed sync spec:

| Tier | What syncs to cloud | Typical size per session |
|---|---|---|
| **Lite** (default) | Distilled restarts + index metadata only | ~2-5KB |
| **Standard** | Lite + raw JSONL, raw expires after 30 days | ~1-10MB |
| **Full** | Everything, counted against 10GB cap | ~1-10MB, persists |

Configured in sync config:
```yaml
sync:
  provider: cloud
  tier: lite
  include:
    adm: true
    restarts: true
    learnings: true
    sops: true
    session_metadata: true
    agent_configs: true
    transcripts: false
```

Storage cap: **10GB per user** (includes R2 version history — old versions of updated files count against the cap). When full, push returns `507 Insufficient Storage`. User must prune or export. The Worker exposes version cleanup via `DELETE /v1/files/{path}/versions?keep=3` to trim old versions.

---

## Rate limiting & cost protection

Five stacking time windows. Limits apply to both request count and bytes transferred.

| Window | Max requests | Max bytes IN | Max bytes OUT | Why |
|---|---|---|---|---|
| Per session (5hr) | 50 | 20MB | 50MB | Matches agent session length |
| Hourly | 30 | 10MB | 30MB | Prevents burst abuse |
| Daily | 200 | 50MB | 100MB | ~4 active sessions/day |
| Weekly | 800 | 200MB | 500MB | Heavy development week |
| Monthly | 2,000 | 500MB | 1GB | Full billing period |

### KV key structure

```
rate:{user_id}:session:{hash}:req     → count (TTL: 5h)
rate:{user_id}:session:{hash}:in      → bytes (TTL: 5h)
rate:{user_id}:session:{hash}:out     → bytes (TTL: 5h)
rate:{user_id}:hour:{YYYY-MM-DD-HH}  → {req, in, out} (TTL: 1h)
rate:{user_id}:day:{YYYY-MM-DD}       → {req, in, out} (TTL: 24h)
rate:{user_id}:week:{YYYY-WW}         → {req, in, out} (TTL: 7d)
rate:{user_id}:month:{YYYY-MM}        → {req, in, out} (TTL: 31d)
```

### Enforcement flow

```
Request → Auth (API key in KV) → Check all 5 rate windows → Process or 429
```

429 responses include which window was exceeded and when it resets.

### Export exemption

`GET /v1/export` always works regardless of rate limits (your data is your data). Limited to 1 export per day to prevent CDN abuse. Returns a signed R2 URL so the download bypasses the Worker.

---

## Stripe billing & account lifecycle

### Pricing

$1.50 USD per quarter. Auto-renews only if the user has made at least one API request in the last 60 days.

### Economics

| Item | Cost per user/quarter |
|---|---|
| Stripe fee (2.9% + $0.30) | $0.34 |
| R2 storage (10GB, 3 months) | ~$0.45 |
| Worker compute | ~$0.01 |
| **Total cost** | **~$0.80** |
| **Revenue** | **$1.50** |
| **Profit** | **~$0.70/user/quarter** |

Profitable from user #1. No fixed infrastructure costs.

### Checkout flow

```
User visits cloud.html
  → Clicks "Get Started"
  → Stripe Checkout ($1.50/quarter subscription)
  → Stripe webhook: checkout.session.completed
    → Worker generates API key: crypto.randomBytes(32).hex()
    → Worker stores SHA-256(key + salt) in KV with user metadata
    → Post-checkout page shows API key (displayed once, never stored raw)
  → User runs: echo "sk_recall_..." > ~/.env/recall/api-key
  → /recall sync init --cloud works
```

### Auto-cancel on inactivity

```
Stripe webhook: invoice.upcoming (~3 days before renewal)
  → Worker checks: any API requests in last 60 days?
  → YES: let Stripe charge normally
  → NO:  cancel subscription via Stripe API
          set KV status to "inactive"
          data retained for 30-day grace period
```

### Account states

| State | Push/pull? | Export? | Data retained? | Trigger |
|---|---|---|---|---|
| **active** | Yes | Yes | Yes | Paid and current |
| **inactive** | No | Yes | 30 days | Auto-cancelled or voluntary |
| **expired** | No | Yes | 7 more days | Grace period ending |
| **deleted** | No | No | No | 37 days post-last-payment, no activity |

Data is always exportable until deletion. Re-activation during grace period restores full access.

### API key security

```
Generation:
  raw_key = crypto.randomBytes(32).hex()     → "sk_recall_a1b2c3..."
  key_hash = SHA-256(raw_key + API_KEY_SALT) → stored in KV

User receives: raw_key (shown once at checkout)
KV stores:     key_hash → { user_id, email, tier, created, expires }
```

- Raw key shown once, never stored by us
- KV only stores the hash
- `API_KEY_SALT` is a Worker secret, not in code
- Key rotation: `POST /v1/auth/rotate` (authenticated with current key)

---

## Agent config versioning

A new sync category for AGENTS.md / CLAUDE.md files. Snapshots are taken on session start and stored as versioned documents in R2.

### What gets stored

```yaml
# agent-configs/CLAUDE.md/2026-03-30T08:01:00.yaml
file: CLAUDE.md
project: myapp
snapshot_date: 2026-03-30T08:01:00
session_id: abc123
changed_by: agent:claude-opus-4-6    # or "human"
diff_summary: "Added 3 rules about ArangoDB env vars"
content: |
  # full file content at this point in time
```

### R2 storage path

```
/{user_id}/agent-configs/
  ├── CLAUDE.md/
  │   └── 2026-03-30T08:01:00.yaml    (R2 versions: 1, 2, 3...)
  └── AGENTS.md/
      └── 2026-03-30T08:01:00.yaml
```

R2 object versioning handles version history automatically. The sync engine snapshots on session start if the file has changed since last snapshot.

### Commands

```bash
/recall configs                     # list tracked agent config files
/recall configs diff                # show what changed since last session
/recall configs rollback 2          # restore from 2 snapshots ago
```

---

## Data isolation & security

- Every R2 object is prefixed with `/{user_id}/` — hard isolation between users
- Worker never serves objects outside the authenticated user's prefix
- No admin API, no cross-user queries
- HTTPS only (Cloudflare Workers enforce this)
- No PII stored beyond email (from Stripe, billing only)
- Session content is opaque to the Worker — stored, not parsed

### If an API key leaks

1. Attacker can read/write that user's sessions only (not other users)
2. Rate limits still apply — can't exfiltrate faster than limits allow
3. User rotates key: `POST /v1/auth/rotate`
4. Storage cap prevents using it as free cloud storage

---

## Microsite

Two new pages alongside the existing microsite, using the same filing cabinet aesthetic:

```
docs/
├── index.html          ← existing recall microsite
├── cloud.html          ← NEW: cloud service + Stripe checkout
└── self-host.html      ← NEW: deploy-your-own guide
```

### cloud.html

- One paragraph: what it does
- Pricing: "$0.50/month. Billed $1.50 quarterly. Auto-cancels if you stop using it."
- Stripe Checkout button
- Post-payment: show API key + setup command
- Link to self-host.html

### self-host.html

Step-by-step deploy-your-own guide:

```
1. Fork the repo
2. Create Cloudflare account (free)
3. Create R2 bucket (enable versioning) + KV namespace
4. Create Stripe account + product
5. Set secrets:
   wrangler secret put STRIPE_SECRET_KEY
   wrangler secret put STRIPE_WEBHOOK_SECRET
   wrangler secret put API_KEY_SALT
6. wrangler deploy
7. Configure Stripe webhook URL
8. Done — selling recall cloud under your own brand
```

### Open source safety

- No credentials in code, ever
- All secrets via `wrangler secret put` (environment variables)
- Self-hosters plug in their own Cloudflare account + Stripe keys
- `.env` files in `.gitignore`

---

## Recall plugin integration

### Config

```yaml
# ~/.config/recall/sync.yaml (same location as git-sync config)
sync:
  provider: cloud
  endpoint: https://recall-api.recall.workers.dev
  api_key_file: ~/.env/recall/api-key
  tier: lite
  auto_sync: true
```

API key lives at `~/.env/recall/api-key` (credential). Config lives at `~/.config/recall/sync.yaml` (not a credential). Self-hosters override `endpoint` to their own Worker URL.

### New commands

| Command | What it does |
|---|---|
| `/recall cloud setup` | Prompt for API key, write config, test connection |
| `/recall cloud status` | Storage, rate limits, billing info |
| `/recall cloud export` | Download full data tarball |

### Sync commands (existing, gain cloud support)

| Command | Behavior with cloud provider |
|---|---|
| `/recall sync push` | PUT changed files to R2 |
| `/recall sync pull` | GET files changed since last pull |
| `/recall sync push --dry-run` | Show what would be pushed |
| `/recall sync --verify` | Confirm all local data is pushed |
| `/recall sync pause` | Pause auto-sync |
| `/recall sync resume` | Resume auto-sync |

### Auto-sync behavior

```
SessionEnd hook fires
  → Index session locally (existing)
  → Cloud configured + auto_sync?
    → YES: push changed files (background, non-blocking, fail silently)
    → NO:  done
  → Rate limited? Queue for next session, log a note
```

Local always works. Cloud is additive. Sync failures never block the user.

---

## File structure (new/modified)

```
recall/
├── worker/                           # NEW: Cloudflare Worker
│   ├── src/
│   │   ├── index.ts                  # Worker entrypoint, router
│   │   ├── auth.ts                   # API key validation
│   │   ├── rate-limiter.ts           # 5-window rate limiting
│   │   ├── files.ts                  # R2 CRUD operations
│   │   ├── stripe.ts                 # Webhook handler
│   │   └── export.ts                 # Signed URL generation
│   ├── wrangler.toml                 # Worker config (R2 binding, KV binding)
│   ├── package.json
│   └── tsconfig.json
├── lib/
│   ├── sync_cloud.py                 # NEW: cloud provider adapter
│   └── sync.py                       # MODIFIED: register cloud provider
├── docs/
│   ├── cloud.html                    # NEW: cloud service page
│   └── self-host.html                # NEW: deploy guide
└── wrangler.toml                     # existing (microsite deploy)
```

---

## Scaling path

The free Worker tier handles 100k requests/day. Planning horizon:

| Users | Est. requests/day | Action needed |
|---|---|---|
| 0-500 | <10k | Free tier, no action |
| 500-2,000 | 10k-50k | Workers paid plan ($5/mo) |
| 2,000-5,000 | 50k-100k | Monitor, approaching free tier limit |
| 5,000+ | >100k | Split read/write Workers, or add caching layer |

At 5,000 paying users: $10,000/quarter revenue. Infrastructure cost: ~$50/month. Comfortable margin for scaling decisions.

---

## Scope: v1 vs v2

### v1 (this spec)

- Cloudflare Worker with auth, rate limiting, R2 storage
- Stripe quarterly billing with auto-cancel on inactivity
- Cloud provider adapter in sync engine
- cloud.html and self-host.html pages
- Agent config snapshotting
- `/recall cloud setup`, `status`, `export` commands
- Open source with self-host documentation

### v2 (future)

- Encryption at rest (client-side, before push)
- Server-side search (Worker-powered full-text search over sessions)
- Usage analytics dashboard (how much storage, which categories)
- Team/shared sync (multi-user access to same R2 prefix)
- Cloudflare affiliate integration if program terms improve
- Continuous sync daemon mode
- Webhook notifications (new session synced, storage near cap)
