# Recall Skill v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement semi-automatic knowledge extraction that persists credentials, tools, gotchas, and workflows to CLAUDE.md files, with cross-project search capability.

**Architecture:** SessionEnd extracts knowledge proposals using local heuristics (always) and Claude API (for complex sessions). User reviews with `/recall learn`. SessionStart loads and displays knowledge. Search falls back to global when local yields no results.

**Tech Stack:** Python 3, JSON storage, Claude API (anthropic SDK), existing hooks infrastructure

---

## Task 1: Knowledge Storage Utilities

Create the foundation for reading/writing CLAUDE.md files.

**Files:**
- Create: `lib/knowledge.py`
- Test: Manual testing via Python REPL

**Step 1: Create the knowledge library**

```python
#!/usr/bin/env python3
"""
CLAUDE.md knowledge management utilities.
Handles reading, writing, and merging knowledge entries.
"""

import os
import re
from pathlib import Path
from typing import Optional

# Category headers in CLAUDE.md
CATEGORIES = ['Credentials', 'Tools', 'Gotchas', 'Workflows']

GLOBAL_CLAUDE_MD = Path.home() / '.claude' / 'CLAUDE.md'


def get_project_claude_md() -> Optional[Path]:
    """Find project CLAUDE.md by looking for .claude/ directory."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / '.claude' / 'CLAUDE.md'
        if candidate.parent.exists():  # .claude dir exists
            return candidate
        # Also check for project root markers
        if (parent / '.git').exists():
            return parent / '.claude' / 'CLAUDE.md'
    return Path.cwd() / '.claude' / 'CLAUDE.md'


def load_claude_md(path: Path) -> dict:
    """Load CLAUDE.md into structured dict by category."""
    result = {cat: [] for cat in CATEGORIES}

    if not path.exists():
        return result

    try:
        content = path.read_text()
    except IOError:
        return result

    current_category = None

    for line in content.split('\n'):
        # Check for category header
        for cat in CATEGORIES:
            if line.strip().startswith(f'## {cat}'):
                current_category = cat
                break
        else:
            # Not a header, add to current category
            if current_category and line.strip().startswith('- '):
                result[current_category].append(line.strip()[2:])

    return result


def save_claude_md(path: Path, knowledge: dict, header: str = "# Knowledge"):
    """Save structured knowledge dict to CLAUDE.md."""
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [header, '']

    for cat in CATEGORIES:
        items = knowledge.get(cat, [])
        if items:
            lines.append(f'## {cat}')
            for item in items:
                lines.append(f'- {item}')
            lines.append('')

    path.write_text('\n'.join(lines))


def add_knowledge(item: str, category: str, scope: str = 'global') -> bool:
    """Add a knowledge item to the appropriate CLAUDE.md."""
    if category not in CATEGORIES:
        return False

    if scope == 'global':
        path = GLOBAL_CLAUDE_MD
        header = '# Global Knowledge'
    else:
        path = get_project_claude_md()
        header = f'# Project Knowledge'

    knowledge = load_claude_md(path)

    # Avoid duplicates
    if item not in knowledge[category]:
        knowledge[category].append(item)
        save_claude_md(path, knowledge, header)

    return True


def get_all_knowledge() -> dict:
    """Load and merge global + project knowledge."""
    global_k = load_claude_md(GLOBAL_CLAUDE_MD)
    project_k = load_claude_md(get_project_claude_md())

    # Merge (project items come after global)
    merged = {}
    for cat in CATEGORIES:
        merged[cat] = global_k.get(cat, []) + project_k.get(cat, [])

    return merged


def format_knowledge_summary(knowledge: dict) -> str:
    """Format knowledge for SessionStart display."""
    lines = []
    for cat in CATEGORIES:
        items = knowledge.get(cat, [])
        if items:
            lines.append(f"  - {cat}: {len(items)} items")
    return '\n'.join(lines) if lines else "  (none)"
```

**Step 2: Verify the library works**

```bash
cd /Users/exampleuser/code/recall-skill && python3 -c "
from lib.knowledge import load_claude_md, save_claude_md, add_knowledge, GLOBAL_CLAUDE_MD
from pathlib import Path

# Test loading existing
k = load_claude_md(GLOBAL_CLAUDE_MD)
print('Loaded categories:', list(k.keys()))
print('Current items:', {c: len(v) for c, v in k.items()})
"
```

Expected: Shows categories and current item counts

**Step 3: Commit**

```bash
git add lib/knowledge.py
git commit -m "feat(recall-v2): add knowledge storage utilities

- load/save CLAUDE.md files
- category-based structure (Credentials, Tools, Gotchas, Workflows)
- global + project scope support

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Pending Learnings Storage

Create storage for proposed learnings awaiting user approval.

**Files:**
- Create: `lib/pending.py`
- Test: Manual testing

**Step 1: Create pending learnings library**

```python
#!/usr/bin/env python3
"""
Pending learnings storage.
Manages proposals awaiting user approval.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

PENDING_FILE = Path.home() / '.claude' / 'pending-learnings.json'


def load_pending() -> dict:
    """Load pending learnings."""
    if not PENDING_FILE.exists():
        return {'version': 1, 'pending': []}

    try:
        return json.loads(PENDING_FILE.read_text())
    except (json.JSONDecodeError, IOError):
        return {'version': 1, 'pending': []}


def save_pending(data: dict):
    """Save pending learnings."""
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(data, indent=2, default=str))


def add_pending(
    category: str,
    title: str,
    content: str,
    session_id: str,
    session_summary: str,
    project: str,
    suggested_scope: str = 'global',
    source: str = 'heuristic'
) -> str:
    """Add a pending learning. Returns the ID."""
    data = load_pending()

    # Check for duplicates (same content)
    for existing in data['pending']:
        if existing.get('content') == content:
            return existing.get('id', '')

    learning_id = str(uuid.uuid4())[:8]

    data['pending'].append({
        'id': learning_id,
        'timestamp': datetime.now().isoformat(),
        'session_id': session_id,
        'session_summary': session_summary[:100],
        'project': project,
        'category': category,
        'title': title,
        'content': content,
        'suggested_scope': suggested_scope,
        'source': source
    })

    save_pending(data)
    return learning_id


def remove_pending(learning_id: str) -> bool:
    """Remove a pending learning by ID."""
    data = load_pending()
    original_len = len(data['pending'])
    data['pending'] = [p for p in data['pending'] if p.get('id') != learning_id]

    if len(data['pending']) < original_len:
        save_pending(data)
        return True
    return False


def get_pending_count() -> int:
    """Get count of pending learnings."""
    data = load_pending()
    return len(data.get('pending', []))


def clear_pending():
    """Clear all pending learnings."""
    save_pending({'version': 1, 'pending': []})
```

**Step 2: Verify it works**

```bash
cd /Users/exampleuser/code/recall-skill && python3 -c "
from lib.pending import load_pending, add_pending, get_pending_count, remove_pending

print('Current pending:', get_pending_count())

# Test add (won't persist if we remove it)
test_id = add_pending(
    category='credentials',
    title='Test credential',
    content='~/.test-creds',
    session_id='test123',
    session_summary='Test session',
    project='test-project'
)
print('Added:', test_id)
print('After add:', get_pending_count())

# Clean up
remove_pending(test_id)
print('After remove:', get_pending_count())
"
```

Expected: Shows add/remove working

**Step 3: Commit**

```bash
git add lib/pending.py
git commit -m "feat(recall-v2): add pending learnings storage

- JSON-based storage at ~/.claude/pending-learnings.json
- add/remove/count operations
- duplicate detection by content

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Local Heuristic Extractor

Create the free extraction that runs on every session.

**Files:**
- Create: `bin/extract-knowledge.py`
- Test: Manual with sample session data

**Step 1: Create the extractor**

```python
#!/usr/bin/env python3
"""
Local heuristic knowledge extractor.
Extracts paths, credentials, tools from session data without API calls.
"""

import re
import sys
import json
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from pending import add_pending


def extract_credential_paths(text: str) -> list:
    """Extract likely credential file paths."""
    patterns = [
        r'~/\.[a-zA-Z0-9_-]*(?:cred|token|key|pass|auth|secret)[a-zA-Z0-9_-]*',
        r'~/\.[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]*(?:cred|token|key|pass|auth)[a-zA-Z0-9_.-]*',
        r'~/.(?:arango|acme|sample|bb)[a-zA-Z0-9_-]*',
    ]

    found = set()
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        found.update(matches)

    return list(found)


def extract_tool_paths(text: str, successful_commands: list) -> list:
    """Extract tool paths from successful commands."""
    tools = set()

    # Look for paths in ~/code/ that are scripts/tools
    pattern = r'~/code/[a-zA-Z0-9_-]+/(?:bin|scripts?|tools?)/[a-zA-Z0-9_.-]+'

    for cmd in successful_commands:
        matches = re.findall(pattern, cmd)
        tools.update(matches)

    # Also look for explicit tool mentions
    tool_pattern = r'~/code/[a-zA-Z0-9_-]+/[a-zA-Z0-9_/-]+\.(?:sh|py|js)'
    for cmd in successful_commands:
        matches = re.findall(tool_pattern, cmd)
        tools.update(matches)

    return list(tools)


def extract_env_files(text: str) -> list:
    """Extract .env and environment file paths."""
    patterns = [
        r'~/\.[a-zA-Z0-9_-]*env[a-zA-Z0-9_/-]*',
        r'~/.demoenv/[a-zA-Z0-9_.-]+',
    ]

    found = set()
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        found.update(matches)

    return list(found)


def is_complex_session(session_data: dict) -> bool:
    """Determine if session needs Claude API analysis."""
    failures = session_data.get('failures', [])
    messages = session_data.get('user_messages', [])
    commands = session_data.get('commands', [])

    # 3+ failures
    if len(failures) >= 3:
        return True

    # Debugging keywords
    debug_keywords = ['why', 'not working', 'figured out', 'root cause',
                      'the problem', 'issue was', 'fixed by', 'solution']
    all_text = ' '.join(m.get('content', '') for m in messages).lower()
    if any(kw in all_text for kw in debug_keywords):
        return True

    # Long session with many tool calls
    if len(messages) >= 10 and len(commands) >= 15:
        return True

    return False


def extract_from_session(session_data: dict, project_folder: str) -> list:
    """Extract knowledge proposals from session data."""
    proposals = []

    session_id = session_data.get('session_id', 'unknown')
    summary = session_data.get('summary', '')[:100]

    # Combine all text for searching
    all_text = ''
    for msg in session_data.get('user_messages', []):
        content = msg.get('content', '') if isinstance(msg, dict) else str(msg)
        all_text += content + '\n'

    # Get successful commands (not in failures)
    failed_cmds = {f.get('command', '') for f in session_data.get('failures', [])}
    successful_cmds = [
        c.get('command', '') for c in session_data.get('commands', [])
        if c.get('command', '') not in failed_cmds
    ]

    # Extract credentials
    creds = extract_credential_paths(all_text)
    for cred in creds:
        proposals.append({
            'category': 'Credentials',
            'title': f'Credential file: {Path(cred).name}',
            'content': cred,
            'suggested_scope': 'global'
        })

    # Extract tools
    tools = extract_tool_paths(all_text, successful_cmds)
    for tool in tools:
        proposals.append({
            'category': 'Tools',
            'title': f'Tool: {Path(tool).name}',
            'content': tool,
            'suggested_scope': 'global'
        })

    # Extract env files
    envs = extract_env_files(all_text)
    for env in envs:
        proposals.append({
            'category': 'Credentials',
            'title': f'Env file: {Path(env).name}',
            'content': env,
            'suggested_scope': 'global'
        })

    return proposals, is_complex_session(session_data)


def main():
    """Process session data from stdin or file argument."""
    if len(sys.argv) > 1:
        session_file = Path(sys.argv[1])
        if session_file.exists():
            session_data = json.loads(session_file.read_text())
        else:
            print(f"File not found: {session_file}", file=sys.stderr)
            sys.exit(1)
    else:
        session_data = json.load(sys.stdin)

    project = sys.argv[2] if len(sys.argv) > 2 else 'unknown'

    proposals, needs_api = extract_from_session(session_data, project)

    # Add proposals to pending
    added = 0
    for p in proposals:
        add_pending(
            category=p['category'],
            title=p['title'],
            content=p['content'],
            session_id=session_data.get('session_id', 'unknown'),
            session_summary=session_data.get('summary', '')[:100],
            project=project,
            suggested_scope=p['suggested_scope'],
            source='heuristic'
        )
        added += 1

    result = {
        'proposals_added': added,
        'needs_api_analysis': needs_api
    }

    print(json.dumps(result))


if __name__ == '__main__':
    main()
```

**Step 2: Test with sample data**

```bash
cd /Users/exampleuser/code/recall-skill && python3 -c "
import json
from bin import sys
sys.path.insert(0, 'bin')
# Can't easily import, just verify file syntax
exec(open('bin/extract-knowledge.py').read().split('if __name__')[0])

# Test extraction functions
text = '''
We found credentials at ~/.arango-dev and ~/.sample-creds.
The tool is at ~/code/demoapp-tools/bitbucket/list-pipelines.sh
Also check ~/.demoenv/laravel-demo.env
'''
creds = extract_credential_paths(text)
print('Credentials found:', creds)

tools = extract_tool_paths(text, ['~/code/demoapp-tools/bitbucket/list-pipelines.sh'])
print('Tools found:', tools)

envs = extract_env_files(text)
print('Env files found:', envs)
"
```

Expected: Shows extracted paths

**Step 3: Commit**

```bash
git add bin/extract-knowledge.py
git commit -m "feat(recall-v2): add local heuristic knowledge extractor

- extracts credential paths (~/.arango-*, ~/.sample-creds, etc)
- extracts tool paths from successful commands
- extracts env file locations
- detects complex sessions needing API analysis

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Integrate Extraction into SessionEnd Hook

Modify index-session.py to call extraction after indexing.

**Files:**
- Modify: `bin/index-session.py:395-405` (after save_index call)
- Test: Manual session end

**Step 1: Add extraction call to index-session.py**

Add after line 395 (after `save_index(project_folder, index)`):

```python
    # === KNOWLEDGE EXTRACTION (v2) ===
    try:
        # Prepare session data for extraction
        extraction_data = {
            'session_id': session_id,
            'summary': session_data['summary'],
            'user_messages': session_data['user_messages'],
            'commands': session_data['commands'],
            'failures': session_data['failures']
        }

        # Run local heuristic extraction
        extract_script = Path(__file__).parent / 'extract-knowledge.py'
        if extract_script.exists():
            import subprocess
            result = subprocess.run(
                ['python3', str(extract_script), '-', project_folder],
                input=json.dumps(extraction_data),
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                extract_result = json.loads(result.stdout)
                proposals = extract_result.get('proposals_added', 0)
                if proposals > 0:
                    print(f"  Proposed {proposals} learnings (run /recall learn to review)")
    except Exception as e:
        # Don't fail indexing if extraction fails
        pass
```

**Step 2: Test by ending a session**

Run a Claude session in recall-skill project, exit, check output

Expected: Shows "Proposed N learnings" if any found

**Step 3: Commit**

```bash
git add bin/index-session.py
git commit -m "feat(recall-v2): integrate knowledge extraction into SessionEnd

- calls extract-knowledge.py after session indexing
- shows proposal count in session end output
- fails silently to not break indexing

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: /recall learn Command

Create the interactive review command.

**Files:**
- Create: `bin/recall-learn.py`
- Modify: `bin/recall-sessions.py:699-734` (add learn command routing)
- Modify: `commands/recall.md` (document new command)

**Step 1: Create recall-learn.py**

```python
#!/usr/bin/env python3
"""
Interactive learning review for /recall learn command.
Shows pending learnings and accepts user input for approval.
"""

import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from pending import load_pending, remove_pending, get_pending_count
from knowledge import add_knowledge, CATEGORIES


def format_learning(learning: dict, index: int) -> str:
    """Format a learning for display."""
    lines = [
        f"### {index}. [{learning['category']}] {learning['title']}",
        f"From: {learning['session_summary']} ({learning['timestamp'][:10]})",
        "",
        f"  {learning['content']}",
        "",
        f"  Suggested: {learning['suggested_scope']}",
        "",
        "  [a]ccept  [A]ccept to {'project' if learning['suggested_scope'] == 'global' else 'global'}  [e]dit  [r]eject  [s]kip"
    ]
    return '\n'.join(lines)


def show_pending():
    """Show all pending learnings for review."""
    data = load_pending()
    pending = data.get('pending', [])

    if not pending:
        print("## No Pending Learnings")
        print()
        print("Knowledge extraction happens automatically at session end.")
        print("Proposals will appear here for your review.")
        return

    print(f"## Pending Learnings ({len(pending)} items)")
    print()
    print("Review each item and choose an action:")
    print("  [a]ccept - Add with suggested scope")
    print("  [A]ccept - Add with opposite scope")
    print("  [e]dit  - Edit content before adding")
    print("  [r]eject - Delete permanently")
    print("  [s]kip  - Keep for later review")
    print()

    for i, learning in enumerate(pending, 1):
        print(format_learning(learning, i))
        print()


def process_action(learning_id: str, action: str, learning: dict) -> str:
    """Process user action on a learning."""
    if action == 'a':
        # Accept with suggested scope
        scope = learning['suggested_scope']
        success = add_knowledge(learning['content'], learning['category'], scope)
        if success:
            remove_pending(learning_id)
            return f"✓ Added to {scope} CLAUDE.md"
        return "✗ Failed to add"

    elif action == 'A':
        # Accept with opposite scope
        scope = 'project' if learning['suggested_scope'] == 'global' else 'global'
        success = add_knowledge(learning['content'], learning['category'], scope)
        if success:
            remove_pending(learning_id)
            return f"✓ Added to {scope} CLAUDE.md"
        return "✗ Failed to add"

    elif action == 'r':
        # Reject
        remove_pending(learning_id)
        return "✓ Rejected and removed"

    elif action == 's':
        # Skip
        return "⏭ Skipped (will appear again)"

    elif action == 'e':
        # Edit - just inform, actual editing needs interactive input
        return "Edit mode not available in batch. Use Claude to edit pending-learnings.json"

    return f"Unknown action: {action}"


def main():
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == '--batch':
        # Batch mode: accept all with suggested scope
        data = load_pending()
        for learning in data.get('pending', []):
            result = process_action(learning['id'], 'a', learning)
            print(f"{learning['title']}: {result}")
        return

    # Show mode (default)
    show_pending()

    # If there are pending items, show hint
    count = get_pending_count()
    if count > 0:
        print("---")
        print("To accept all with suggested scope: `/recall learn --batch`")
        print("To review interactively, Claude will process your responses.")


if __name__ == '__main__':
    main()
```

**Step 2: Add routing to recall-sessions.py**

Add after line 730 (in the command handling section), before the else (search):

```python
        elif cmd_name == 'learn':
            # Run the learn script
            learn_script = Path(__file__).parent / 'recall-learn.py'
            if learn_script.exists():
                import subprocess
                args = ['python3', str(learn_script)]
                if cmd_arg:
                    args.append(cmd_arg)
                subprocess.run(args)
            else:
                print("Learn script not found. Check installation.")
```

**Step 3: Update commands/recall.md**

Add to the usage section:

```markdown
- `/recall learn` - Review and approve pending learnings
- `/recall learn --batch` - Accept all pending learnings with suggested scope
- `/recall knowledge` - Show currently loaded knowledge
```

**Step 4: Test the command**

```bash
cd /Users/exampleuser/code/recall-skill && python3 bin/recall-learn.py
```

Expected: Shows "No Pending Learnings" or list of pending items

**Step 5: Commit**

```bash
git add bin/recall-learn.py bin/recall-sessions.py commands/recall.md
git commit -m "feat(recall-v2): add /recall learn command

- interactive review of pending learnings
- accept/reject/skip/edit actions
- batch mode for quick approval
- integrated into /recall command routing

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 6: /recall knowledge Command

Show what's currently loaded in CLAUDE.md.

**Files:**
- Modify: `bin/recall-sessions.py` (add knowledge command)
- Modify: `commands/recall.md`

**Step 1: Add knowledge command to recall-sessions.py**

Add in the command handling section:

```python
        elif cmd_name == 'knowledge':
            # Show current knowledge
            try:
                sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
                from knowledge import get_all_knowledge, GLOBAL_CLAUDE_MD, get_project_claude_md

                print("## Current Knowledge")
                print()
                print(f"**Global:** `{GLOBAL_CLAUDE_MD}`")
                print(f"**Project:** `{get_project_claude_md()}`")
                print()

                knowledge = get_all_knowledge()
                for cat, items in knowledge.items():
                    if items:
                        print(f"### {cat}")
                        for item in items:
                            print(f"  - {item}")
                        print()

                if not any(knowledge.values()):
                    print("No knowledge loaded yet.")
                    print("Use `/recall learn` to review and approve pending learnings.")
            except ImportError as e:
                print(f"Knowledge library not found: {e}")
```

**Step 2: Test**

```bash
cd /Users/exampleuser/code/recall-skill && python3 bin/recall-sessions.py "$PWD" knowledge
```

Expected: Shows knowledge or "No knowledge loaded"

**Step 3: Commit**

```bash
git add bin/recall-sessions.py commands/recall.md
git commit -m "feat(recall-v2): add /recall knowledge command

- shows global and project CLAUDE.md contents
- organized by category

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Enhanced SessionStart

Update session-context.py to show knowledge summary.

**Files:**
- Modify: `bin/session-context.py:77-118`

**Step 1: Add knowledge loading to session-context.py**

Replace the output section (around line 77) with:

```python
    output = []
    output.append("## Session Context from /recall")
    output.append("")

    # Show last session summary
    last_session_id, last_session = sorted_sessions[0]
    time_ago = format_time_ago(last_session.get('date', ''))

    output.append(f"**Last session** ({time_ago}): {last_session.get('summary', 'No summary')[:150]}")

    # Show stats
    total_sessions = len(sessions)
    total_failures = sum(s.get('failure_count', 0) for s in sessions.values())

    if total_sessions > 1:
        output.append(f"**History**: {total_sessions} sessions, {total_failures} total failures")

    # Show knowledge summary (v2)
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
        from knowledge import get_all_knowledge, format_knowledge_summary
        from pending import get_pending_count

        knowledge = get_all_knowledge()
        has_knowledge = any(knowledge.values())

        if has_knowledge:
            output.append("")
            output.append("**Knowledge loaded:**")
            output.append(format_knowledge_summary(knowledge))

        pending = get_pending_count()
        if pending > 0:
            output.append("")
            output.append(f"**Pending:** {pending} learnings awaiting review (`/recall learn`)")
    except ImportError:
        pass  # Knowledge library not installed

    # Show recurring failure patterns (if any)
    # ... rest of existing code ...
```

**Step 2: Test**

```bash
cd /Users/exampleuser/code/recall-skill && python3 bin/session-context.py "$PWD"
```

Expected: Shows knowledge summary if any exists, pending count if any

**Step 3: Commit**

```bash
git add bin/session-context.py
git commit -m "feat(recall-v2): enhanced SessionStart with knowledge summary

- shows loaded knowledge counts by category
- shows pending learnings reminder
- graceful fallback if library not installed

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Cross-Project Search

Add global search when local search finds nothing.

**Files:**
- Modify: `bin/recall-sessions.py:573-640` (search_sessions function)

**Step 1: Add cross-project search to recall-sessions.py**

Replace the search_sessions function:

```python
def list_all_project_indices() -> list:
    """List all project folders with recall indices."""
    projects_dir = Path.home() / '.claude' / 'projects'
    if not projects_dir.exists():
        return []

    projects = []
    for proj_dir in projects_dir.iterdir():
        if proj_dir.is_dir():
            index_file = proj_dir / 'recall-index.json'
            if index_file.exists():
                projects.append(proj_dir.name)
    return projects


def search_sessions(search_term: str, index: dict, sessions: list, project_folder: str):
    """Search for term across sessions.

    Smart routing: searches local first, offers global if no results.
    """
    print(f"## Searching for: '{search_term}'")
    print()

    found = False
    search_lower = search_term.lower()

    # Search current project first
    if index and index.get('sessions'):
        sorted_sessions = sorted(
            index['sessions'].items(),
            key=lambda x: x[1].get('date', ''),
            reverse=True
        )

        for session_id, session_summary in sorted_sessions[:20]:
            matches = []
            details = load_session_details(project_folder, session_id)

            if details:
                for msg in details.get('user_messages', []):
                    content = msg.get('content', '') if isinstance(msg, dict) else str(msg)
                    if search_lower in content.lower():
                        matches.append(content)
            else:
                summary = session_summary.get('summary', '')
                if search_lower in summary.lower():
                    matches.append(summary)

            if matches:
                found = True
                print(f"### {format_date(session_summary.get('date', ''))} ({session_id[:8]}...)")
                for match in matches[:3]:
                    print(f"  > {match[:200]}...")
                print()

    if found:
        return

    # No local results - search other projects
    print(f"No results in current project ({project_folder[-30:]}).")
    print()

    all_projects = list_all_project_indices()
    other_projects = [p for p in all_projects if p != project_folder]

    if not other_projects:
        print("No other projects to search.")
        return

    global_results = []

    for proj in other_projects:
        proj_index = load_index(proj)
        if not proj_index:
            continue

        proj_sessions = proj_index.get('sessions', {})
        matches_in_proj = []

        for session_id, session_summary in proj_sessions.items():
            summary = session_summary.get('summary', '')
            if search_lower in summary.lower():
                matches_in_proj.append({
                    'session_id': session_id,
                    'date': session_summary.get('date', ''),
                    'summary': summary
                })

            # Also search details if available
            details = load_session_details(proj, session_id)
            if details:
                for msg in details.get('user_messages', []):
                    content = msg.get('content', '') if isinstance(msg, dict) else str(msg)
                    if search_lower in content.lower() and session_id not in [m['session_id'] for m in matches_in_proj]:
                        matches_in_proj.append({
                            'session_id': session_id,
                            'date': session_summary.get('date', ''),
                            'summary': content[:150]
                        })

        if matches_in_proj:
            global_results.append({
                'project': proj,
                'matches': matches_in_proj
            })

    if global_results:
        print(f"Found matches in {len(global_results)} other project(s):")
        print()
        for result in global_results:
            proj_name = result['project'].split('-')[-1] if '-' in result['project'] else result['project']
            print(f"### {proj_name} ({len(result['matches'])} matches)")
            for match in result['matches'][:3]:
                print(f"  > [{match['date'][:10]}] {match['summary'][:150]}...")
            if len(result['matches']) > 3:
                print(f"  ... and {len(result['matches']) - 3} more")
            print()
    else:
        print(f"No matches found for '{search_term}' in any project.")
```

**Step 2: Test cross-project search**

```bash
cd /Users/exampleuser/code/recall-skill && python3 bin/recall-sessions.py "$PWD" sample
```

Expected: Shows "No results in current project" then "Found matches in rcm-support"

**Step 3: Commit**

```bash
git add bin/recall-sessions.py
git commit -m "feat(recall-v2): add cross-project search

- searches local project first
- falls back to all other projects if no local results
- shows matches grouped by project

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 9: Seed Initial Knowledge

Populate CLAUDE.md with knowledge from the ArangoDB debugging session.

**Files:**
- Write: `~/.claude/CLAUDE.md` (via the knowledge library)

**Step 1: Add initial knowledge programmatically**

```bash
cd /Users/exampleuser/code/recall-skill && python3 -c "
import sys
sys.path.insert(0, 'lib')
from knowledge import add_knowledge

# Credentials
add_knowledge('ArangoDB dev: ~/.arango-dev', 'Credentials', 'global')
add_knowledge('ArangoDB prod: ~/.arango-prod', 'Credentials', 'global')
add_knowledge('ArangoDB replica: ~/.arango-prod-replica (read-only, http://52.87.179.123:8529)', 'Credentials', 'global')
add_knowledge('Sample: ~/.sample-creds', 'Credentials', 'global')
add_knowledge('Acme: ~/.acme/', 'Credentials', 'global')
add_knowledge('Bitbucket token: ~/.bb-cli-personal-token', 'Credentials', 'global')
add_knowledge('Laravel env: ~/.demoenv/laravel-demo.env', 'Credentials', 'global')

# Tools
add_knowledge('Bitbucket CLI scripts: ~/code/demoapp-tools/bitbucket/', 'Tools', 'global')
add_knowledge('AWS profiles: kare-dev-admin, kare-prod-admin (note: kare not demo)', 'Tools', 'global')

# Gotchas
add_knowledge('Shell ARANGO_* env vars override Laravel .env - unset before artisan', 'Gotchas', 'global')
add_knowledge('Bitbucket repos at git@bitbucket.org:demoapp/ - use bb tools not gh', 'Gotchas', 'global')

print('Initial knowledge seeded to ~/.claude/CLAUDE.md')
"
```

**Step 2: Verify**

```bash
cat ~/.claude/CLAUDE.md
```

Expected: Shows structured knowledge file

**Step 3: Commit the library (knowledge was written to user's home, not repo)**

```bash
cd /Users/exampleuser/code/recall-skill
git add -A
git commit -m "feat(recall-v2): complete implementation

Phase 1-5 implemented:
- Knowledge storage utilities
- Pending learnings storage
- Local heuristic extraction
- /recall learn command
- /recall knowledge command
- Enhanced SessionStart
- Cross-project search

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 10: Update Install Script

Ensure new files are installed properly.

**Files:**
- Modify: `install.sh`

**Step 1: Add new files to install.sh**

Add to the symlink section:

```bash
# Lib directory (new in v2)
mkdir -p "$CLAUDE_DIR/lib"
ln -sf "$SKILL_DIR/lib/knowledge.py" "$CLAUDE_DIR/lib/"
ln -sf "$SKILL_DIR/lib/pending.py" "$CLAUDE_DIR/lib/"
ln -sf "$SKILL_DIR/lib/__init__.py" "$CLAUDE_DIR/lib/" 2>/dev/null || touch "$CLAUDE_DIR/lib/__init__.py"

# New v2 scripts
ln -sf "$SKILL_DIR/bin/extract-knowledge.py" "$CLAUDE_DIR/bin/"
ln -sf "$SKILL_DIR/bin/recall-learn.py" "$CLAUDE_DIR/bin/"
```

**Step 2: Test installation**

```bash
cd /Users/exampleuser/code/recall-skill && ./install.sh
```

Expected: Installs without errors

**Step 3: Commit**

```bash
git add install.sh
git commit -m "feat(recall-v2): update install script for v2 files

- installs lib/knowledge.py and lib/pending.py
- installs new v2 bin scripts

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Summary

After completing all tasks:

1. **Knowledge extraction** runs automatically at session end
2. **`/recall learn`** lets you review and approve extracted knowledge
3. **`/recall knowledge`** shows what's loaded
4. **Cross-project search** finds sessions across all projects
5. **SessionStart** shows knowledge summary and pending count
6. **Initial knowledge** seeded from your ArangoDB debugging session

Test the full flow:
1. Start a new Claude session
2. Mention some credentials or tools in conversation
3. Exit the session
4. Check `/recall learn` for proposals
5. Accept them
6. Start new session - should see knowledge loaded
