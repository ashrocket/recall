# Recall Skill v2 Design

**Date:** 2026-01-27
**Status:** Approved

## Problem Statement

The current recall skill indexes sessions but fails to:
1. **Extract knowledge** - `"learnings": []` everywhere, wisdom dies with each session
2. **Surface knowledge** - Credential locations, tool paths not available at session start
3. **Search cross-project** - Can't find sample work from rcm-support when in different directory
4. **Learn from debugging** - Shell env override pattern discovered but never saved

### Concrete Failure Example

In a acme-app session, Claude spent significant time debugging ArangoDB connection issues despite:
- `~/.arango-dev`, `~/.arango-prod`, `~/.arango-prod-replica` credential files existing
- The "shell env vars override .env" pattern being solved in previous sessions
- `~/.demoenv/laravel-demo.env` being the standard env file location

This knowledge existed in past sessions but was never extracted or surfaced.

## Design Goals

1. **Behavioral learning** - Claude gets smarter about how to work, not just remembers what happened
2. **Semi-automatic extraction** - Propose learnings, user approves (no noise, stays in control)
3. **Instant knowledge** - Credentials, tools, gotchas available immediately at session start
4. **Cross-project discovery** - Find relevant sessions regardless of current directory

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     RECALL SKILL v2                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SessionStart Hook                                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 1. Load ~/.claude/CLAUDE.md (global knowledge)          │   │
│  │ 2. Load .claude/CLAUDE.md (project knowledge)           │   │
│  │ 3. Show session context + relevant warnings             │   │
│  │ 4. Remind about pending learnings                       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  SessionEnd Hook                                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 1. Index session (existing)                             │   │
│  │ 2. Local heuristics: extract paths, credentials, tools  │   │
│  │ 3. If complex session: Claude API extracts patterns     │   │
│  │ 4. Write proposals to pending-learnings.json            │   │
│  │ 5. Show "N learnings proposed" summary                  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  /recall Command                                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ /recall              - List recent sessions             │   │
│  │ /recall <term>       - Search (local first, then global)│   │
│  │ /recall learn        - Review/approve pending learnings │   │
│  │ /recall last         - Previous session details         │   │
│  │ /recall failures     - Show SOPs + failure patterns     │   │
│  │ /recall knowledge    - Show what's in CLAUDE.md         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Knowledge Storage                                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ~/.claude/CLAUDE.md         - Global (credentials,tools)│   │
│  │ .claude/CLAUDE.md           - Per-project               │   │
│  │ ~/.claude/shell-failures/sops.json - Error→fix patterns │   │
│  │ ~/.claude/pending-learnings.json   - Awaiting approval  │   │
│  │ ~/.claude/projects/*/recall-index.json - Session index  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Cross-Project Search                                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 1. Search current project index                         │   │
│  │ 2. If no results: scan all project indices              │   │
│  │ 3. Prompt: "Found N matches in <project> - show them?"  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Knowledge storage | Hybrid: CLAUDE.md + SOPs + search | High-freq knowledge instant, patterns in SOPs, deep memory via search |
| Extraction mode | Semi-automatic | Fully auto = noise; fully manual = never happens |
| Analysis trigger | Hybrid (local + Claude API) | Most sessions simple (free heuristics), complex sessions need Claude |
| Cross-project search | Smart routing | Fast local path, discovers cross-project when needed |
| CLAUDE.md structure | Flat categories | Simple to auto-generate and merge |
| Items routing | Smart defaults | Reduce friction, override when needed |

## Detailed Component Designs

### 1. CLAUDE.md Structure

Four flat categories, auto-maintained:

**Global `~/.claude/CLAUDE.md`:**
```markdown
# Global Knowledge

## Credentials
- ArangoDB dev: ~/.arango-dev
- ArangoDB prod: ~/.arango-prod
- ArangoDB replica: ~/.arango-prod-replica
- Sample: ~/.sample-creds
- Acme: ~/.acme/
- Bitbucket token: ~/.bb-cli-personal-token

## Tools
- Bitbucket CLI: ~/code/demoapp-tools/bitbucket/
- AWS profiles: kare-dev-admin, kare-prod-admin (note: kare not demo)

## Gotchas
- Shell env vars can override Laravel .env files - unset ARANGO_* before running artisan
- Bitbucket repos use git@bitbucket.org:demoapp/ not github

## Workflows
- For Laravel dev: source ~/.demoenv/laravel-demo.env first
```

**Per-project `.claude/CLAUDE.md`:**
```markdown
# Project: rcm-support

## Tools
- Acme eligibility: ~/code/rcm-support/acme-app/
- Check eligibility: python3 check_eligibility.py --payer "BCBS NC" ...

## Workflows
- Dev API runs at http://127.0.0.1:8000
- Mock auth: REACT_APP_MOCK_AUTH=true
```

### 2. SessionEnd Extraction

#### Local Heuristics (always run, free)

```python
def extract_local(session_data):
    extractions = []

    # Credential files: ~/.*creds, ~/.*token, ~/.*/
    for msg in session_data['user_messages']:
        paths = re.findall(r'~/\.[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_.-]*)?', msg)
        for path in paths:
            if any(kw in path.lower() for kw in ['cred', 'token', 'key', 'pass', 'auth']):
                extractions.append({
                    'category': 'credentials',
                    'content': path,
                    'source': 'heuristic'
                })

    # Tool paths from successful commands
    for cmd in session_data['commands']:
        if '/code/' in cmd['command'] and cmd not in failures:
            tool_path = extract_tool_path(cmd['command'])
            if tool_path:
                extractions.append({
                    'category': 'tools',
                    'content': tool_path,
                    'source': 'heuristic'
                })

    # Error→fix pairs (feed to SOP system)
    # ... existing SOP detection logic ...

    return extractions
```

#### Claude API Triggers

Call Claude API for semantic extraction when ANY of:
- Session has 3+ failures
- Session contains debugging keywords: "why", "not working", "figured out", "root cause", "the problem was"
- Session duration > 30 minutes with 10+ tool calls
- User explicitly ran `/recall analyze`

#### Claude API Extraction Prompt

```
Analyze this Claude Code session and extract reusable knowledge.

Session summary: {summary}
User messages: {messages}
Commands and results: {commands}
Failures and resolutions: {failures}

Extract ONLY concrete, reusable facts in these categories:

1. CREDENTIALS - File paths containing credentials, tokens, keys
2. TOOLS - Script locations, CLI tools, helper utilities
3. GOTCHAS - Non-obvious behaviors, common mistakes, environment quirks
4. WORKFLOWS - Multi-step processes that should be repeated

For each extraction, provide:
- category: credentials|tools|gotchas|workflows
- title: Short description (5-10 words)
- content: The actual knowledge
- scope: global|project (credentials/tools usually global, workflows usually project)

Return JSON array. Only extract CONCRETE facts, not general advice.
```

### 3. Pending Learnings Storage

`~/.claude/pending-learnings.json`:
```json
{
  "version": 1,
  "pending": [
    {
      "id": "abc123",
      "timestamp": "2026-01-27T10:30:00Z",
      "session_id": "xyz789",
      "session_summary": "Acme eligibility debugging",
      "project": "-Users-exampleuser-code-acme-app",
      "category": "credentials",
      "title": "ArangoDB credential files",
      "content": "~/.arango-dev (dev), ~/.arango-prod (prod), ~/.arango-prod-replica (replica)",
      "suggested_scope": "global",
      "source": "claude_api"
    },
    {
      "id": "def456",
      "timestamp": "2026-01-27T10:30:00Z",
      "session_id": "xyz789",
      "session_summary": "Acme eligibility debugging",
      "project": "-Users-exampleuser-code-acme-app",
      "category": "gotchas",
      "title": "Shell env vars override Laravel .env",
      "content": "Shell ARANGO_* env vars override Laravel's .env file. Fix: unset ARANGO_ENDPOINT ARANGO_PASSWORD ARANGO_USERNAME ARANGO_DATABASE before running artisan",
      "suggested_scope": "global",
      "source": "claude_api"
    }
  ]
}
```

### 4. /recall learn Command

Interactive review flow:

```
$ /recall learn

## Pending Learnings (3 items)

### 1. [Credentials] ArangoDB credential files
From: acme-app debugging (2026-01-27)

  ~/.arango-dev      → Dev database
  ~/.arango-prod     → Prod database
  ~/.arango-prod-replica → Read-only replica

  Suggested: global

  [a]ccept  [A]ccept to project  [e]dit  [r]eject  [s]kip

> a

✓ Added to ~/.claude/CLAUDE.md under Credentials

### 2. [Gotchas] Shell env vars override Laravel .env
...
```

**Keyboard shortcuts:**
- `a` - Accept with suggested scope
- `A` - Accept with opposite scope (if suggested global, accept to project)
- `e` - Edit content before accepting
- `r` - Reject (delete from pending)
- `s` - Skip (keep in pending for later)
- `q` - Quit review

### 5. Cross-Project Search

```python
def search_sessions(term, project_folder):
    # Step 1: Search current project
    results = search_project_index(project_folder, term)

    if results:
        return {'source': 'local', 'results': results}

    # Step 2: Search all projects
    all_projects = list_all_project_indices()
    global_results = []

    for proj in all_projects:
        if proj != project_folder:
            matches = search_project_index(proj, term)
            if matches:
                global_results.append({
                    'project': proj,
                    'matches': matches
                })

    if global_results:
        return {
            'source': 'global',
            'results': global_results,
            'prompt': f"No local results. Found matches in {len(global_results)} other projects."
        }

    return {'source': 'none', 'results': []}
```

Output when cross-project results found:
```
## Search: "sample"

No results in current project (recall-skill).

Found 5 matches in other projects:
  - rcm-support: 3 sessions (most recent: 2026-01-25)
  - code: 2 sessions (most recent: 2026-01-24)

Show results from [a]ll  [r]cm-support  [c]ode  [n]one?
```

### 6. SessionStart Output

Enhanced output showing loaded knowledge:

```
## Session Context from /recall

**Project:** rcm-support (18 sessions, last: 7h ago)
**Last session:** Acme eligibility UI - API routes, reverify button

**Knowledge loaded:**
  - Credentials: 4 items (ArangoDB, Acme, Bitbucket, Sample)
  - Tools: 3 items
  - Gotchas: 2 items

**Recent patterns in this project:**
  - Python traceback (3x this week)
  - ArangoDB connection issues (2x) - see Gotchas

**Pending:** 2 learnings awaiting review (`/recall learn`)

_Use `/recall` to search, `/recall knowledge` to see loaded items_
```

## File Changes

### New Files
- `bin/recall-learn.py` - Interactive learning review
- `bin/extract-knowledge.py` - Local heuristics extraction
- `lib/claude_extractor.py` - Claude API extraction (when triggered)
- `lib/knowledge.py` - CLAUDE.md read/write utilities

### Modified Files
- `bin/session-context.py` - Enhanced SessionStart output
- `bin/index-session.py` - Add extraction step at SessionEnd
- `bin/recall-sessions.py` - Add cross-project search, `/recall learn` routing
- `commands/recall.md` - Document new subcommands

### Storage Files (created at runtime)
- `~/.claude/CLAUDE.md` - Global knowledge (auto-maintained)
- `~/.claude/pending-learnings.json` - Awaiting approval
- `.claude/CLAUDE.md` - Per-project knowledge (auto-maintained)

## Implementation Phases

### Phase 1: Knowledge Infrastructure
- [ ] CLAUDE.md read/write utilities
- [ ] Pending learnings storage
- [ ] `/recall knowledge` command
- [ ] `/recall learn` interactive review

### Phase 2: Local Extraction
- [ ] Heuristic extractors (paths, credentials, tools)
- [ ] Integration into SessionEnd hook
- [ ] Write proposals to pending-learnings.json

### Phase 3: Claude API Extraction
- [ ] Complex session detection
- [ ] Claude API extraction prompt
- [ ] Semantic pattern extraction (gotchas, workflows)

### Phase 4: Cross-Project Search
- [ ] Federated search across all indices
- [ ] Smart routing (local first, suggest global)
- [ ] Interactive project selection

### Phase 5: Enhanced SessionStart
- [ ] Load and display knowledge summary
- [ ] Show relevant warnings from patterns
- [ ] Pending learnings reminder

## Success Criteria

1. **Knowledge persists** - Credentials discovered in one session available in next
2. **Patterns learned** - "Shell env override" gotcha saved and surfaced
3. **Cross-project works** - Find sample sessions from any directory
4. **No noise** - Only approved items enter CLAUDE.md
5. **Low friction** - Learning review is quick (single keystrokes)

## Future Considerations

- Export/import knowledge bundles for sharing
- Knowledge decay (mark stale items that haven't been useful)
- Team knowledge sync (shared CLAUDE.md for org)
- Integration with MCP servers for external knowledge sources
