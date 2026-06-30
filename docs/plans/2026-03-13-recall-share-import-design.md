# Recall Share & Import — Design

## Problem

No good way to share Claude Code session context with teammates. `/export` produces unsanitized plain text with no import path. Raw JSONL contains secrets and absolute paths.

## Solution

Two new recall subcommands:

- **`/recall share`** — sanitize current session, build portable artifacts, open summary for user approval, save zip
- **`/recall import`** — unzip or parse plain text, merge into local recall index with source marker

Publishing (Confluence, Cloudflare, Slack) is out of scope — recall produces the zip, user publishes however they want.

## Command Flow

### `/recall share [--session <id>]`

```
1. Resolve session (current live JSONL, or by session ID)
2. Sanitize (built-in defaults + .recall-sanitize.yml overrides)
3. Build artifacts:
   - summary.md      — condensed narrative + sanitization report
   - session.json    — recall-compatible structured data
   - transcript.txt  — sanitized /export-style full transcript
4. Open summary.md for user review ($EDITOR or stdout)
   - Sanitizations called out with counts by type
5. User approves
6. Package → zip saved to ./recall-shares/
```

### `/recall import <file>`

```
1. Detect input type (zip or plain text)
2. If zip: unzip, validate manifest
3. If plain text: best-effort parse into recall format (lossy)
4. Merge session.json into local recall-index.json
   - Source marker: "source": "import", "sharer": "<name>"
   - Session ID prefixed: imported-<original_id>
5. Save detail file to recall-sessions/
6. Store transcript.txt alongside for deep dives
7. Print import summary
```

## Zip Package Format

```
recall-share-YYYY-MM-DD-<topic>.zip
├── manifest.json        # Metadata: sharer, project, date, recall version
├── summary.md           # Condensed narrative + sanitization report
├── session.json         # Recall-compatible structured data
└── transcript.txt       # Sanitized /export-style full transcript
```

### manifest.json

```json
{
  "version": 1,
  "sharer": "ashley",
  "project": "demo-dashboard",
  "date": "2026-03-13T14:32:00",
  "session_id": "abc123",
  "recall_version": "2.0.0",
  "sanitization_report": {
    "total_redactions": 47,
    "by_type": { "absolute_paths": 29, "api_tokens": 3, "passwords": 1 }
  }
}
```

## Sanitizer

Runs once upstream — all three artifacts derived from cleaned data.

### Built-in Rules (always on unless disabled)

| Pattern | Example | Replacement |
|---|---|---|
| Absolute home paths | `/Users/whoever/...` | `~/...` |
| API keys/tokens | `sk-...`, `xoxb-...`, Bearer | `[REDACTED_TOKEN]` |
| Passwords in commands | `-u "user:pass"` | `-u "[REDACTED_CREDS]"` |
| Env secrets | `DB_PASSWORD=xyz` | `DB_PASSWORD=[REDACTED]` |
| SSH/PEM keys | `-----BEGIN RSA...` | `[REDACTED_KEY]` |

### Optional Rules (off by default)

- IP addresses
- Email addresses
- AWS instance IDs

### Custom Rules via `.recall-sanitize.yml`

```yaml
rules:
  absolute_paths: true
  api_tokens: true
  passwords_in_commands: true
  env_secrets: true
  ssh_keys: true
  ip_addresses: false
  email_addresses: false
  aws_instance_ids: false
  custom:
    - pattern: "demoapp\\.com"
      replacement: "[INTERNAL_DOMAIN]"
      label: "Internal domains"
```

Located in project root or `~/.claude/`. Project-level overrides merge with defaults.

### Sanitization Report

Included in summary.md:

```
## Sanitization Report
Sanitized 47 items:
  12x absolute paths → ~/...
   3x API tokens
   1x password in curl command
   2x custom: internal domains
  29x home dir references
```

## Import Behavior

Imported sessions appear in recall like any other session:

```
**2026-03-13** [imported from ashley] auth-refactor
  42 msgs, 3 failures | Key topics: JWT, middleware, Redis
```

SessionStart hook surfaces them automatically. Search finds them. Learnings and failure patterns merge into the index.

## File Layout (new/changed in recall-skill)

### New Files

```
bin/recall-share.py          # Share command: sanitize -> package -> approve
bin/recall-import.py         # Import command: unzip -> merge into index
lib/sanitizer.py             # Sanitizer engine + pattern matching
defaults/sanitize-defaults.yml  # Built-in sanitization rules
```

### Changed Files

```
commands/recall.md           # Add share/import subcommands to routing
lib/shared.py                # Add helpers: get_shares_dir(), load_manifest(), session-to-text
bin/recall-sessions.py       # Show imported sessions with [imported from X] tag
```

### Unchanged

```
hooks/*                      # SessionStart already picks up anything in the index
lib/knowledge.py             # Learnings from imported sessions just work
migrations/                  # Index version stays at 2
```

## Decisions

- **Approach B**: Recall owns sanitize/package/approve. Publishing is external.
- **Plain text fallback**: `/recall import` accepts raw `/export` output without zip. Best-effort parse, lossy but functional.
- **No index version bump**: Imported sessions are regular entries with extra `source`/`sharer` fields. Backward compatible.
- **Sanitizer runs once**: All artifacts derived from same cleaned data. No risk of one artifact leaking what another redacted.
