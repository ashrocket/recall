# Recall Share & Import Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `/recall share` and `/recall import` subcommands so teammates can exchange sanitized session context through portable zip packages.

**Architecture:** Sanitizer engine (`lib/sanitizer.py`) strips secrets from raw JSONL data. Share script (`bin/recall-share.py`) packages sanitized data into 3 artifacts (summary.md, session.json, transcript.txt) inside a zip. Import script (`bin/recall-import.py`) unzips and merges into local recall index. Command routing in `recall.md` dispatches `share`/`import` to these scripts vs existing `recall-sessions.py`.

**Tech Stack:** Python 3, stdlib only (json, re, zipfile, yaml parsing manual or via included PyYAML-free parser)

---

### Task 1: Sanitizer Engine — Core Pattern Matching

**Files:**
- Create: `lib/sanitizer.py`
- Create: `tests/test_sanitizer.py`

**Step 1: Write failing tests for built-in sanitization rules**

```python
# tests/test_sanitizer.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from sanitizer import Sanitizer

class TestAbsolutePaths:
    def test_home_dir_replaced(self):
        s = Sanitizer()
        text = "Reading /Users/exampleuser/code/project/file.py"
        result = s.sanitize_text(text)
        assert "/Users/exampleuser" not in result
        assert "~/code/project/file.py" in result

    def test_other_user_home_replaced(self):
        s = Sanitizer()
        text = "Found at /home/ubuntu/app/config.yml"
        result = s.sanitize_text(text)
        assert "/home/ubuntu" not in result
        assert "~/app/config.yml" in result

    def test_non_home_absolute_path_kept(self):
        s = Sanitizer()
        text = "Using /usr/bin/python3"
        result = s.sanitize_text(text)
        assert "/usr/bin/python3" in result  # System paths are fine

class TestApiTokens:
    def test_sk_token_redacted(self):
        s = Sanitizer()
        text = 'key = "sk-ant-abc123def456"'
        result = s.sanitize_text(text)
        assert "sk-ant-abc123def456" not in result
        assert "[REDACTED_TOKEN]" in result

    def test_bearer_token_redacted(self):
        s = Sanitizer()
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"
        result = s.sanitize_text(text)
        assert "eyJhbGciOiJIUzI1NiJ9" not in result
        assert "[REDACTED_TOKEN]" in result

    def test_xoxb_slack_token_redacted(self):
        s = Sanitizer()
        text = "SLACK_TOKEN=xoxb-123456789-abcdef"
        result = s.sanitize_text(text)
        assert "xoxb-123456789" not in result

class TestPasswords:
    def test_curl_password_redacted(self):
        s = Sanitizer()
        text = 'curl -u "admin:s3cretP@ss" https://api.example.com'
        result = s.sanitize_text(text)
        assert "s3cretP@ss" not in result
        assert "[REDACTED_CREDS]" in result

    def test_password_env_var_redacted(self):
        s = Sanitizer()
        text = "DB_PASSWORD=hunter2"
        result = s.sanitize_text(text)
        assert "hunter2" not in result
        assert "[REDACTED]" in result

class TestSshKeys:
    def test_private_key_redacted(self):
        s = Sanitizer()
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAK...\n-----END RSA PRIVATE KEY-----"
        result = s.sanitize_text(text)
        assert "MIIEpAIBAAK" not in result
        assert "[REDACTED_KEY]" in result

class TestSanitizationReport:
    def test_report_tracks_counts(self):
        s = Sanitizer()
        text = "/Users/ash/file.py has key sk-abc123 and /Users/ash/other.py"
        s.sanitize_text(text)
        report = s.get_report()
        assert report['total_redactions'] >= 3
        assert 'absolute_paths' in report['by_type']
        assert 'api_tokens' in report['by_type']
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_sanitizer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sanitizer'`

**Step 3: Implement the sanitizer**

```python
# lib/sanitizer.py
"""Sanitize session data by removing secrets, credentials, and absolute paths."""

import re
from pathlib import Path
from typing import Optional

# Built-in rules — each returns (compiled_regex, replacement_string, label)
_BUILTIN_RULES = {
    'absolute_paths': {
        'enabled': True,
        'patterns': [
            # /Users/username/... or /home/username/... → ~/...
            (re.compile(r'/(?:Users|home)/[^/\s]+/'), '~/', 'Home directory path'),
        ],
        'label': 'absolute paths'
    },
    'api_tokens': {
        'enabled': True,
        'patterns': [
            # sk-ant-..., sk-..., anthropic keys
            (re.compile(r'\bsk-(?:ant-)?[A-Za-z0-9_-]{10,}\b'), '[REDACTED_TOKEN]', 'API key'),
            # Bearer tokens
            (re.compile(r'Bearer\s+[A-Za-z0-9._-]{20,}'), 'Bearer [REDACTED_TOKEN]', 'Bearer token'),
            # Slack tokens
            (re.compile(r'\bxox[bpras]-[A-Za-z0-9-]{10,}\b'), '[REDACTED_TOKEN]', 'Slack token'),
            # Generic long hex/base64 tokens after = or :
            (re.compile(r'(?<=(?:token|key|secret|password|apikey|api_key)\s{0,3}[=:]\s{0,3})["\']?[A-Za-z0-9+/=_-]{20,}["\']?', re.IGNORECASE),
             '[REDACTED_TOKEN]', 'Generic token'),
        ],
        'label': 'API tokens'
    },
    'passwords_in_commands': {
        'enabled': True,
        'patterns': [
            # curl -u "user:password"
            (re.compile(r'-u\s+["\']?([^:"\'\s]+):([^"\'>\s]+)["\']?'), '-u "[REDACTED_CREDS]"', 'curl password'),
            # --password=... or --passwd=...
            (re.compile(r'--pass(?:word|wd)\s*[=]\s*\S+'), '--password=[REDACTED]', 'CLI password'),
        ],
        'label': 'passwords in commands'
    },
    'env_secrets': {
        'enabled': True,
        'patterns': [
            # DB_PASSWORD=value, SECRET_KEY=value, etc (env-style)
            (re.compile(r'\b([A-Z_]*(?:PASSWORD|SECRET|TOKEN|KEY|CREDENTIAL|AUTH)[A-Z_]*)\s*=\s*([^\s"\']{3,})'),
             r'\1=[REDACTED]', 'Environment secret'),
        ],
        'label': 'environment secrets'
    },
    'ssh_keys': {
        'enabled': True,
        'patterns': [
            # PEM private keys (multiline)
            (re.compile(r'-----BEGIN\s+(?:RSA\s+|DSA\s+|EC\s+|OPENSSH\s+)?PRIVATE KEY-----[\s\S]*?-----END\s+(?:RSA\s+|DSA\s+|EC\s+|OPENSSH\s+)?PRIVATE KEY-----'),
             '[REDACTED_KEY]', 'SSH/PEM key'),
        ],
        'label': 'SSH keys'
    },
    'ip_addresses': {
        'enabled': False,  # Off by default
        'patterns': [
            (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '[REDACTED_IP]', 'IP address'),
        ],
        'label': 'IP addresses'
    },
    'email_addresses': {
        'enabled': False,
        'patterns': [
            (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), '[REDACTED_EMAIL]', 'Email address'),
        ],
        'label': 'email addresses'
    },
    'aws_instance_ids': {
        'enabled': False,
        'patterns': [
            (re.compile(r'\bi-[0-9a-f]{8,17}\b'), '[REDACTED_INSTANCE]', 'AWS instance ID'),
        ],
        'label': 'AWS instance IDs'
    },
}


class Sanitizer:
    """Sanitize text by applying configurable redaction rules."""

    def __init__(self, config_path: Optional[Path] = None):
        self.rules = {}
        self.custom_rules = []
        self.report = {'total_redactions': 0, 'by_type': {}}

        # Load built-in rules
        for name, rule in _BUILTIN_RULES.items():
            self.rules[name] = {
                'enabled': rule['enabled'],
                'patterns': rule['patterns'],
                'label': rule['label'],
            }

        # Load config overrides
        if config_path:
            self._load_config(config_path)
        else:
            # Auto-discover config
            for candidate in [
                Path.cwd() / '.recall-sanitize.yml',
                Path.home() / '.claude' / '.recall-sanitize.yml',
            ]:
                if candidate.exists():
                    self._load_config(candidate)
                    break

    def _load_config(self, config_path: Path):
        """Load YAML config (minimal parser, no PyYAML dependency)."""
        try:
            text = config_path.read_text()
            # Simple YAML parser for our flat structure
            in_custom = False
            current_custom = None

            for line in text.split('\n'):
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue

                if stripped == 'custom:':
                    in_custom = True
                    continue

                if in_custom:
                    if stripped.startswith('- pattern:'):
                        if current_custom:
                            self.custom_rules.append(current_custom)
                        pattern_val = stripped.split(':', 1)[1].strip().strip('"\'')
                        current_custom = {'pattern': pattern_val, 'replacement': '[REDACTED]', 'label': 'custom'}
                    elif stripped.startswith('replacement:') and current_custom:
                        current_custom['replacement'] = stripped.split(':', 1)[1].strip().strip('"\'')
                    elif stripped.startswith('label:') and current_custom:
                        current_custom['label'] = stripped.split(':', 1)[1].strip().strip('"\'')
                    elif not stripped.startswith('-') and not stripped.startswith(' '):
                        # Exited custom block
                        if current_custom:
                            self.custom_rules.append(current_custom)
                            current_custom = None
                        in_custom = False
                else:
                    # Top-level rule toggle
                    if ':' in stripped:
                        key, val = stripped.split(':', 1)
                        key = key.strip()
                        val = val.strip().lower()
                        if key in self.rules:
                            self.rules[key]['enabled'] = val in ('true', 'yes', '1')

            if current_custom:
                self.custom_rules.append(current_custom)

        except Exception:
            pass  # Config errors are non-fatal

    def sanitize_text(self, text: str) -> str:
        """Apply all enabled rules to text. Track redaction counts."""
        result = text

        # Apply built-in rules
        for name, rule in self.rules.items():
            if not rule['enabled']:
                continue
            for pattern, replacement, _label in rule['patterns']:
                matches = pattern.findall(result)
                if matches:
                    count = len(matches)
                    result = pattern.sub(replacement, result)
                    self.report['total_redactions'] += count
                    self.report['by_type'][name] = self.report['by_type'].get(name, 0) + count

        # Apply custom rules
        for custom in self.custom_rules:
            try:
                pattern = re.compile(custom['pattern'])
                matches = pattern.findall(result)
                if matches:
                    count = len(matches)
                    result = pattern.sub(custom['replacement'], result)
                    label = f"custom: {custom['label']}"
                    self.report['total_redactions'] += count
                    self.report['by_type'][label] = self.report['by_type'].get(label, 0) + count
            except re.error:
                continue

        return result

    def sanitize_dict(self, data: dict) -> dict:
        """Recursively sanitize all string values in a dict."""
        import copy
        result = copy.deepcopy(data)
        self._sanitize_recursive(result)
        return result

    def _sanitize_recursive(self, obj):
        """Walk a data structure, sanitizing strings in-place."""
        if isinstance(obj, dict):
            for key in obj:
                if isinstance(obj[key], str):
                    obj[key] = self.sanitize_text(obj[key])
                elif isinstance(obj[key], (dict, list)):
                    self._sanitize_recursive(obj[key])
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, str):
                    obj[i] = self.sanitize_text(item)
                elif isinstance(item, (dict, list)):
                    self._sanitize_recursive(item)

    def get_report(self) -> dict:
        """Return sanitization report with counts by type."""
        return dict(self.report)

    def format_report(self) -> str:
        """Return human-readable sanitization report."""
        if self.report['total_redactions'] == 0:
            return "No sensitive data found."
        lines = [f"Sanitized {self.report['total_redactions']} items:"]
        for rule_name, count in sorted(self.report['by_type'].items(), key=lambda x: -x[1]):
            label = self.rules.get(rule_name, {}).get('label', rule_name)
            lines.append(f"  {count:3d}x {label}")
        return '\n'.join(lines)
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_sanitizer.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
cd ~/ashcode/recall-skill
git add lib/sanitizer.py tests/test_sanitizer.py
git commit -m "feat: add sanitizer engine with configurable redaction rules"
```

---

### Task 2: Sanitizer — Config File & Custom Rules

**Files:**
- Create: `defaults/sanitize-defaults.yml`
- Modify: `tests/test_sanitizer.py` (add config tests)

**Step 1: Write failing tests for config loading**

```python
# Add to tests/test_sanitizer.py
import tempfile
import os

class TestConfigLoading:
    def test_enable_optional_rule(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write("ip_addresses: true\n")
            f.flush()
            s = Sanitizer(config_path=Path(f.name))
        os.unlink(f.name)
        text = "Server at 192.168.1.100 responded"
        result = s.sanitize_text(text)
        assert "192.168.1.100" not in result

    def test_disable_builtin_rule(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write("absolute_paths: false\n")
            f.flush()
            s = Sanitizer(config_path=Path(f.name))
        os.unlink(f.name)
        text = "/Users/someone/code/file.py"
        result = s.sanitize_text(text)
        assert "/Users/someone" in result  # NOT redacted

    def test_custom_pattern(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write('custom:\n  - pattern: "demoapp\\\\.com"\n    replacement: "[INTERNAL]"\n    label: "Internal domains"\n')
            f.flush()
            s = Sanitizer(config_path=Path(f.name))
        os.unlink(f.name)
        text = "API at https://v3-api-dev.demoapp.com:3000"
        result = s.sanitize_text(text)
        assert "demoapp.com" not in result
        assert "[INTERNAL]" in result
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_sanitizer.py::TestConfigLoading -v`
Expected: FAIL (if Task 1 config loading not fully working) or PASS (if Task 1 already covers this). Either way, verify.

**Step 3: Create defaults file**

```yaml
# defaults/sanitize-defaults.yml
# Built-in sanitization rules for /recall share
# Override per-project with .recall-sanitize.yml in project root or ~/.claude/

rules:
  # Always on
  absolute_paths: true
  api_tokens: true
  passwords_in_commands: true
  env_secrets: true
  ssh_keys: true

  # Off by default — enable per-project
  ip_addresses: false
  email_addresses: false
  aws_instance_ids: false

  # Add project-specific patterns:
  # custom:
  #   - pattern: "mycompany\\.com"
  #     replacement: "[INTERNAL_DOMAIN]"
  #     label: "Company domains"
```

**Step 4: Run full test suite**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_sanitizer.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
cd ~/ashcode/recall-skill
git add defaults/sanitize-defaults.yml tests/test_sanitizer.py
git commit -m "feat: add sanitizer config file and custom rule support"
```

---

### Task 3: Share Script — Session Resolution & JSONL-to-Text

**Files:**
- Create: `bin/recall-share.py`
- Modify: `lib/shared.py` (add `get_shares_dir()`, `session_to_transcript()`)
- Create: `tests/test_share.py`

**Step 1: Write failing tests for shared helpers**

```python
# tests/test_share.py
import sys
import json
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from shared import get_shares_dir, session_to_transcript

class TestGetSharesDir:
    def test_returns_path(self):
        result = get_shares_dir()
        assert isinstance(result, Path)
        assert result.name == 'recall-shares'

class TestSessionToTranscript:
    def test_basic_transcript(self):
        session_data = {
            'user_messages': [
                {'content': 'Fix the login bug', 'timestamp': '2026-03-13T10:00:00'},
            ],
            'commands': [
                {'command': 'grep -r "login" src/', 'tool_id': 'abc'},
            ],
            'summary': 'Fix login bug',
        }
        result = session_to_transcript(session_data)
        assert 'Fix the login bug' in result
        assert 'grep -r "login" src/' in result

    def test_empty_session(self):
        result = session_to_transcript({'user_messages': [], 'commands': [], 'summary': ''})
        assert isinstance(result, str)
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_share.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_shares_dir'`

**Step 3: Add helpers to shared.py**

Add after `get_agents_file()` (around line 236 in `lib/shared.py`):

```python
def get_shares_dir(project_folder: str = None) -> Path:
    """Return the directory for shared session packages."""
    return get_project_dir(project_folder) / 'recall-shares'


def session_to_transcript(session_data: dict) -> str:
    """Convert structured session data to plain-text transcript.

    Produces an /export-style readable transcript from parsed session data.
    """
    lines = []
    date = session_data.get('date', 'unknown date')
    summary = session_data.get('summary', 'Untitled session')
    lines.append(f"# Session: {summary}")
    lines.append(f"Date: {date}")
    lines.append("")

    messages = session_data.get('user_messages', [])
    commands = session_data.get('commands', [])
    failures = session_data.get('failures', [])

    # Interleave messages and commands by index for chronological order
    all_items = []
    for msg in messages:
        all_items.append(('message', msg.get('index', 0), msg))
    for cmd in commands:
        all_items.append(('command', cmd.get('index', 0), cmd))
    all_items.sort(key=lambda x: x[1])

    for item_type, _idx, item in all_items:
        if item_type == 'message':
            lines.append(f"## User")
            lines.append(item.get('content', ''))
            lines.append("")
        elif item_type == 'command':
            lines.append(f"## Command")
            lines.append(f"```bash")
            lines.append(item.get('command', ''))
            lines.append(f"```")
            # Check if this command failed
            cmd_text = item.get('command', '')
            for fail in failures:
                if fail.get('command', '') == cmd_text:
                    lines.append(f"**Error:** {fail.get('error', '')[:200]}")
            lines.append("")

    if session_data.get('topics'):
        lines.append(f"## Topics")
        lines.append(', '.join(session_data['topics']))
        lines.append("")

    return '\n'.join(lines)
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_share.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
cd ~/ashcode/recall-skill
git add lib/shared.py tests/test_share.py
git commit -m "feat: add session transcript helper and shares directory path"
```

---

### Task 4: Share Script — Package Builder

**Files:**
- Create: `bin/recall-share.py`
- Modify: `tests/test_share.py` (add packaging tests)

**Step 1: Write failing tests for the packager**

```python
# Add to tests/test_share.py
import zipfile

class TestBuildPackage:
    def test_creates_zip_with_all_artifacts(self):
        from recall_share import build_package  # We'll adjust import path

        session_data = {
            'session_id': 'test123',
            'date': '2026-03-13T10:00:00',
            'summary': '[brainstorming] auth refactor',
            'user_messages': [{'content': 'Refactor auth', 'timestamp': '2026-03-13T10:00:00', 'index': 0}],
            'commands': [{'command': 'ls src/auth/', 'tool_id': 'cmd1', 'index': 1}],
            'failures': [],
            'topics': ['auth', 'JWT'],
            'skills_used': [],
        }
        sanitization_report = {'total_redactions': 0, 'by_type': {}}

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = build_package(session_data, sanitization_report, Path(tmpdir), sharer='testuser')
            assert zip_path.exists()
            assert zip_path.suffix == '.zip'

            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert 'manifest.json' in names
                assert 'summary.md' in names
                assert 'session.json' in names
                assert 'transcript.txt' in names

                # Verify manifest
                manifest = json.loads(zf.read('manifest.json'))
                assert manifest['version'] == 1
                assert manifest['sharer'] == 'testuser'
                assert manifest['session_id'] == 'test123'
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_share.py::TestBuildPackage -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement recall-share.py**

```python
#!/usr/bin/env python3
"""recall-share: Package a session for sharing with teammates.

Usage:
    recall-share.py <project_path> [--session <id>] [--sharer <name>]

Produces a zip in recall-shares/ containing:
  - manifest.json    (metadata + sanitization report)
  - summary.md       (condensed narrative for humans)
  - session.json     (recall-importable structured data)
  - transcript.txt   (sanitized full transcript)
"""

import json
import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from shared import (
    get_project_folder, get_shares_dir, load_index,
    load_session_details, get_session_details_dir,
    session_to_transcript,
)
from sanitizer import Sanitizer


def resolve_session(project_folder: str, session_id: str = None) -> dict:
    """Resolve session data — from detail file or by parsing JSONL.

    If session_id is None, uses the most recent session.
    """
    if session_id:
        # Try detail file first
        details = load_session_details(project_folder, session_id)
        if details:
            return details

    # Fall back to index for most recent
    index = load_index(project_folder)
    if not index or not index.get('sessions'):
        print("No sessions found in index.")
        sys.exit(1)

    if not session_id:
        # Get most recent
        sessions = index['sessions']
        session_id = max(sessions.keys(), key=lambda k: sessions[k].get('date', ''))

    details = load_session_details(project_folder, session_id)
    if not details:
        print(f"No detail file found for session {session_id}")
        # Return minimal data from index
        idx_entry = index['sessions'].get(session_id, {})
        return {
            'session_id': session_id,
            'date': idx_entry.get('date', datetime.now().isoformat()),
            'summary': idx_entry.get('summary', ''),
            'user_messages': [],
            'commands': [],
            'failures': [],
            'topics': idx_entry.get('topics', []),
            'skills_used': [],
        }
    return details


def build_summary_md(session_data: dict, sanitization_report: dict, sharer: str) -> str:
    """Build the human-readable summary markdown."""
    lines = []
    lines.append(f"# Session Share: {session_data.get('summary', 'Untitled')}")
    lines.append("")
    lines.append(f"**Shared by:** {sharer}")
    lines.append(f"**Date:** {session_data.get('date', 'unknown')}")
    msg_count = len(session_data.get('user_messages', []))
    cmd_count = len(session_data.get('commands', []))
    fail_count = len(session_data.get('failures', []))
    lines.append(f"**Stats:** {msg_count} messages, {cmd_count} commands, {fail_count} failures")
    lines.append("")

    # Topics
    topics = session_data.get('topics', [])
    if topics:
        lines.append(f"**Topics:** {', '.join(topics[:10])}")
        lines.append("")

    # Key messages (user messages, summarized)
    messages = session_data.get('user_messages', [])
    if messages:
        lines.append("## Conversation Highlights")
        lines.append("")
        for msg in messages[:15]:  # Cap at 15
            content = msg.get('content', '')
            if len(content) > 5:
                lines.append(f"- {content}")
        lines.append("")

    # Commands run
    commands = session_data.get('commands', [])
    if commands:
        lines.append("## Commands Run")
        lines.append("")
        for cmd in commands[:20]:  # Cap at 20
            lines.append(f"- `{cmd.get('command', '')}`")
        lines.append("")

    # Failures
    failures = session_data.get('failures', [])
    if failures:
        lines.append("## Failures Encountered")
        lines.append("")
        for fail in failures[:10]:
            lines.append(f"- `{fail.get('command', '')}` — {fail.get('error', '')[:100]}")
        lines.append("")

    # Sanitization report
    lines.append("## Sanitization Report")
    lines.append("")
    total = sanitization_report.get('total_redactions', 0)
    if total == 0:
        lines.append("No sensitive data found.")
    else:
        lines.append(f"Sanitized {total} items:")
        for rule_name, count in sorted(
            sanitization_report.get('by_type', {}).items(), key=lambda x: -x[1]
        ):
            lines.append(f"  {count:3d}x {rule_name}")
    lines.append("")

    lines.append("---")
    lines.append(f"*Packaged by recall v2.0.0 on {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    return '\n'.join(lines)


def build_session_json(session_data: dict, sharer: str) -> dict:
    """Build recall-importable session.json."""
    return {
        'session_id': session_data.get('session_id', 'unknown'),
        'date': session_data.get('date', ''),
        'summary': session_data.get('summary', ''),
        'source': 'import',
        'sharer': sharer,
        'user_messages': session_data.get('user_messages', []),
        'commands': session_data.get('commands', []),
        'failures': session_data.get('failures', []),
        'failure_patterns': session_data.get('failure_patterns', {}),
        'topics': session_data.get('topics', []),
        'skills_used': session_data.get('skills_used', []),
    }


def build_package(
    session_data: dict,
    sanitization_report: dict,
    output_dir: Path,
    sharer: str = 'unknown',
) -> Path:
    """Build the zip package with all 3 artifacts + manifest."""
    # Generate slug from summary
    summary = session_data.get('summary', 'session')
    # Strip skill tags like [brainstorming]
    slug_text = re.sub(r'\[.*?\]', '', summary).strip()
    # Take first 4 words, lowercase, hyphenate
    words = re.findall(r'[a-zA-Z0-9]+', slug_text)[:4]
    slug = '-'.join(w.lower() for w in words) if words else 'session'
    date_str = datetime.now().strftime('%Y-%m-%d')

    filename = f"recall-share-{date_str}-{slug}.zip"
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / filename

    # Build artifacts
    manifest = {
        'version': 1,
        'sharer': sharer,
        'project': session_data.get('project', ''),
        'date': session_data.get('date', datetime.now().isoformat()),
        'session_id': session_data.get('session_id', 'unknown'),
        'recall_version': '2.0.0',
        'sanitization_report': sanitization_report,
    }

    summary_md = build_summary_md(session_data, sanitization_report, sharer)
    session_json = build_session_json(session_data, sharer)
    transcript = session_to_transcript(session_data)

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('manifest.json', json.dumps(manifest, indent=2, default=str))
        zf.writestr('summary.md', summary_md)
        zf.writestr('session.json', json.dumps(session_json, indent=2, default=str))
        zf.writestr('transcript.txt', transcript)

    return zip_path


def main():
    if len(sys.argv) < 2:
        print("Usage: recall-share.py <project_path> [--session <id>] [--sharer <name>]")
        sys.exit(1)

    cwd = sys.argv[1]
    session_id = None
    sharer = os.environ.get('USER', 'unknown')

    # Parse args
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == '--session' and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        elif args[i] == '--sharer' and i + 1 < len(args):
            sharer = args[i + 1]
            i += 2
        else:
            i += 1

    project_folder = get_project_folder(cwd)

    # Step 1: Resolve session
    print(f"Resolving session...")
    session_data = resolve_session(project_folder, session_id)
    session_data['project'] = project_folder

    # Step 2: Sanitize
    sanitizer = Sanitizer()
    session_data = sanitizer.sanitize_dict(session_data)
    report = sanitizer.get_report()

    # Step 3: Build summary for review
    summary_md = build_summary_md(session_data, report, sharer)

    # Print summary for user review
    print()
    print(summary_md)
    print()

    # Step 4: Package
    shares_dir = get_shares_dir(project_folder)
    zip_path = build_package(session_data, report, shares_dir, sharer)

    print(f"## Package Created")
    print(f"**File:** `{zip_path}`")
    print(f"**Size:** {zip_path.stat().st_size / 1024:.1f} KB")
    print()
    print("Share this zip with teammates. They import with:")
    print(f"  `/recall import {zip_path.name}`")


if __name__ == '__main__':
    main()
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_share.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
cd ~/ashcode/recall-skill
git add bin/recall-share.py tests/test_share.py
git commit -m "feat: add recall-share.py packager with sanitized zip output"
```

---

### Task 5: Import Script — Zip & Plain Text

**Files:**
- Create: `bin/recall-import.py`
- Create: `tests/test_import.py`

**Step 1: Write failing tests**

```python
# tests/test_import.py
import sys
import json
import tempfile
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'bin'))

class TestImportZip:
    def test_import_valid_zip(self):
        from recall_import import parse_zip_package

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / 'test-share.zip'
            manifest = {
                'version': 1,
                'sharer': 'alice',
                'session_id': 'sess123',
                'date': '2026-03-13T10:00:00',
                'recall_version': '2.0.0',
                'sanitization_report': {'total_redactions': 0, 'by_type': {}},
            }
            session = {
                'session_id': 'sess123',
                'date': '2026-03-13T10:00:00',
                'summary': 'Auth refactor',
                'source': 'import',
                'sharer': 'alice',
                'user_messages': [{'content': 'Fix auth', 'index': 0}],
                'commands': [],
                'failures': [],
                'topics': ['auth'],
            }
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.writestr('manifest.json', json.dumps(manifest))
                zf.writestr('session.json', json.dumps(session))
                zf.writestr('summary.md', '# Test')
                zf.writestr('transcript.txt', 'User: Fix auth')

            result = parse_zip_package(zip_path)
            assert result['manifest']['sharer'] == 'alice'
            assert result['session']['session_id'] == 'sess123'
            assert result['transcript'] == 'User: Fix auth'

class TestImportPlainText:
    def test_parse_plain_transcript(self):
        from recall_import import parse_plain_text

        text = "Human: Fix the login bug in src/auth.py\n\nAssistant: I'll look into the auth module.\n\nHuman: Also check the session handler"
        result = parse_plain_text(text)
        assert len(result['user_messages']) == 2
        assert 'login bug' in result['user_messages'][0]['content']

class TestMergeIntoIndex:
    def test_merge_adds_session_with_source_marker(self):
        from recall_import import merge_into_index

        index = {
            'version': 2,
            'sessions': {},
            'failure_patterns': {},
            'learnings': [],
            'pending_learnings': [],
            'usage': {'skills': {}, 'learnings_shown': {}},
        }
        session = {
            'session_id': 'sess123',
            'date': '2026-03-13T10:00:00',
            'summary': 'Auth refactor',
            'source': 'import',
            'sharer': 'alice',
            'user_messages': [{'content': 'Fix auth', 'index': 0}],
            'commands': [],
            'failures': [],
            'failure_patterns': {},
            'topics': ['auth'],
        }
        merge_into_index(index, session)
        assert 'imported-sess123' in index['sessions']
        entry = index['sessions']['imported-sess123']
        assert entry['source'] == 'import'
        assert entry['sharer'] == 'alice'
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_import.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement recall-import.py**

```python
#!/usr/bin/env python3
"""recall-import: Import a shared session package into local recall index.

Usage:
    recall-import.py <project_path> <file>

Accepts:
  - .zip file (from /recall share) — full structured import
  - .txt/.md file — plain text /export transcript, best-effort parse
"""

import json
import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from shared import (
    get_project_folder, load_index, save_index,
    get_session_details_dir,
)


def parse_zip_package(zip_path: Path) -> dict:
    """Parse a recall share zip package."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        result = {}

        if 'manifest.json' in names:
            result['manifest'] = json.loads(zf.read('manifest.json'))
        else:
            raise ValueError("Invalid package: missing manifest.json")

        if 'session.json' in names:
            result['session'] = json.loads(zf.read('session.json'))
        else:
            raise ValueError("Invalid package: missing session.json")

        if 'summary.md' in names:
            result['summary'] = zf.read('summary.md').decode('utf-8')

        if 'transcript.txt' in names:
            result['transcript'] = zf.read('transcript.txt').decode('utf-8')

    return result


def parse_plain_text(text: str) -> dict:
    """Best-effort parse of a plain text /export transcript.

    Extracts user messages, commands, and topics. Lossy by design.
    """
    result = {
        'session_id': f"imported-text-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        'date': datetime.now().isoformat(),
        'summary': '',
        'source': 'import-plaintext',
        'sharer': 'unknown',
        'user_messages': [],
        'commands': [],
        'failures': [],
        'failure_patterns': {},
        'topics': [],
        'skills_used': [],
    }

    lines = text.split('\n')
    current_speaker = None
    current_content = []

    for line in lines:
        # Detect speaker changes
        if line.startswith('Human:') or line.startswith('User:'):
            # Save previous message
            if current_speaker == 'user' and current_content:
                content = '\n'.join(current_content).strip()
                if content:
                    result['user_messages'].append({
                        'content': content[:200],
                        'index': len(result['user_messages']),
                        'timestamp': result['date'],
                    })
            current_speaker = 'user'
            current_content = [line.split(':', 1)[1].strip()]
        elif line.startswith('Assistant:') or line.startswith('Claude:'):
            if current_speaker == 'user' and current_content:
                content = '\n'.join(current_content).strip()
                if content:
                    result['user_messages'].append({
                        'content': content[:200],
                        'index': len(result['user_messages']),
                        'timestamp': result['date'],
                    })
            current_speaker = 'assistant'
            current_content = [line.split(':', 1)[1].strip()]
        elif line.startswith('$ ') or line.startswith('```bash'):
            # Extract commands
            cmd = line.lstrip('$ ').strip()
            if cmd and cmd != '```bash':
                result['commands'].append({
                    'command': cmd[:150],
                    'index': len(result['commands']),
                    'tool_id': '',
                })
        else:
            current_content.append(line)

    # Save last message
    if current_speaker == 'user' and current_content:
        content = '\n'.join(current_content).strip()
        if content:
            result['user_messages'].append({
                'content': content[:200],
                'index': len(result['user_messages']),
                'timestamp': result['date'],
            })

    # Generate summary from first meaningful message
    if result['user_messages']:
        result['summary'] = result['user_messages'][0]['content'][:150]

    # Extract topics (capitalized words, file paths)
    all_text = text[:5000]
    words = re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b', all_text)
    paths = re.findall(r'[\w./~-]+\.(?:py|js|ts|json|sh|md|yml|yaml)\b', all_text)
    result['topics'] = list(set(words[:5] + [p.split('/')[-1] for p in paths[:5]]))[:10]

    return result


def merge_into_index(index: dict, session_data: dict):
    """Merge imported session data into the recall index.

    Adds session with 'imported-' prefix and source/sharer markers.
    """
    original_id = session_data.get('session_id', 'unknown')
    imported_id = f"imported-{original_id}" if not original_id.startswith('imported-') else original_id

    # Create index summary entry
    index['sessions'][imported_id] = {
        'date': session_data.get('date', datetime.now().isoformat()),
        'summary': session_data.get('summary', '')[:200],
        'message_count': len(session_data.get('user_messages', [])),
        'command_count': len(session_data.get('commands', [])),
        'failure_count': len(session_data.get('failures', [])),
        'skill_count': len(session_data.get('skills_used', [])),
        'topics': session_data.get('topics', [])[:10],
        'has_details': True,
        'source': session_data.get('source', 'import'),
        'sharer': session_data.get('sharer', 'unknown'),
    }

    # Merge failure patterns
    for pattern, entries in session_data.get('failure_patterns', {}).items():
        if pattern not in index['failure_patterns']:
            index['failure_patterns'][pattern] = []
        for entry in entries:
            entry['session_id'] = imported_id
            entry['date'] = session_data.get('date', '')
            entry['count'] = entry.get('count', 1)
            index['failure_patterns'][pattern].append(entry)
        # Keep last 15
        index['failure_patterns'][pattern] = index['failure_patterns'][pattern][-15:]


def main():
    if len(sys.argv) < 3:
        print("Usage: recall-import.py <project_path> <file>")
        print("  <file> can be a .zip (from /recall share) or .txt/.md (plain text)")
        sys.exit(1)

    cwd = sys.argv[1]
    import_file = Path(sys.argv[2])

    # Resolve relative paths
    if not import_file.is_absolute():
        import_file = Path(cwd) / import_file

    if not import_file.exists():
        print(f"Error: File not found: {import_file}")
        sys.exit(1)

    project_folder = get_project_folder(cwd)
    index = load_index(project_folder, create_if_missing=True)

    if import_file.suffix == '.zip':
        # Zip import
        try:
            package = parse_zip_package(import_file)
        except (ValueError, zipfile.BadZipFile) as e:
            print(f"Error: Invalid zip package: {e}")
            sys.exit(1)

        session_data = package['session']
        manifest = package['manifest']
        sharer = manifest.get('sharer', 'unknown')
        session_data['sharer'] = sharer
        session_data['source'] = 'import'

        # Merge into index
        merge_into_index(index, session_data)

        # Save detail file
        details_dir = get_session_details_dir(project_folder)
        details_dir.mkdir(parents=True, exist_ok=True)
        original_id = session_data.get('session_id', 'unknown')
        imported_id = f"imported-{original_id}" if not original_id.startswith('imported-') else original_id
        detail_file = details_dir / f"{imported_id}.json"
        with open(detail_file, 'w') as f:
            json.dump(session_data, f, indent=2, default=str)

        # Save transcript alongside if present
        if package.get('transcript'):
            transcript_file = details_dir / f"{imported_id}.transcript.txt"
            transcript_file.write_text(package['transcript'])

        save_index(index, project_folder)

        report = manifest.get('sanitization_report', {})
        msg_count = len(session_data.get('user_messages', []))
        cmd_count = len(session_data.get('commands', []))
        fail_count = len(session_data.get('failures', []))

        print(f"## Imported Session")
        print(f"**From:** {sharer}")
        print(f"**Summary:** {session_data.get('summary', '')[:100]}")
        print(f"**Stats:** {msg_count} messages, {cmd_count} commands, {fail_count} failures")
        if report.get('total_redactions', 0) > 0:
            print(f"**Note:** {report['total_redactions']} items were sanitized before sharing")

    else:
        # Plain text import
        text = import_file.read_text()
        session_data = parse_plain_text(text)

        merge_into_index(index, session_data)

        # Save detail file
        details_dir = get_session_details_dir(project_folder)
        details_dir.mkdir(parents=True, exist_ok=True)
        detail_file = details_dir / f"{session_data['session_id']}.json"
        with open(detail_file, 'w') as f:
            json.dump(session_data, f, indent=2, default=str)

        # Save original text
        transcript_file = details_dir / f"{session_data['session_id']}.transcript.txt"
        transcript_file.write_text(text)

        save_index(index, project_folder)

        msg_count = len(session_data.get('user_messages', []))
        print(f"## Imported Plain Text Session")
        print(f"**Parsed:** {msg_count} messages (best-effort, may be lossy)")
        print(f"**Summary:** {session_data.get('summary', '')[:100]}")
        print(f"**Note:** Plain text import has limited structure. Zip packages are preferred.")


if __name__ == '__main__':
    main()
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_import.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
cd ~/ashcode/recall-skill
git add bin/recall-import.py tests/test_import.py
git commit -m "feat: add recall-import.py with zip and plain text support"
```

---

### Task 6: Command Routing — Wire share/import into recall.md

**Files:**
- Modify: `commands/recall.md` (add share and import dispatch)

**Step 1: Verify current routing (read-only)**

Read `commands/recall.md` lines 38-49 to confirm dispatch structure.

**Step 2: Add share/import routing**

Insert after the `save` dispatch block (after line 44) and before the "Otherwise" block:

```markdown
**If** `$ARGUMENTS` starts with **`share`**: Run the share script:
```
python3 ${CLAUDE_PLUGIN_ROOT}/bin/recall-share.py "$PWD" $REMAINING_ARGS
```
After the script prints the summary, ask the user to review it. If they approve, confirm the zip location. If they want changes, let them edit and re-run.

**If** `$ARGUMENTS` starts with **`import`** and the argument is a `.zip` file or `.txt`/`.md` file: Run the import script:
```
python3 ${CLAUDE_PLUGIN_ROOT}/bin/recall-import.py "$PWD" <file_path>
```
Note: `/recall import <file.json>` (without .zip) still routes to `recall-sessions.py` for index backup restore.
```

Also update the Usage section at the top to include:
```
- `/recall share` - Package current session for sharing with teammates
- `/recall share --session <id>` - Package a specific session
- `/recall import <file.zip>` - Import a shared session package
- `/recall import <file.txt>` - Import from plain text transcript (lossy)
```

**Step 3: Run manual test**

Run: `cd ~/ashcode/recall-skill && python3 bin/recall-share.py "$(pwd)"`
Expected: Prints summary markdown + creates zip file

**Step 4: Commit**

```bash
cd ~/ashcode/recall-skill
git add commands/recall.md
git commit -m "feat: wire share/import subcommands into recall command routing"
```

---

### Task 7: Display Imported Sessions — Update recall-sessions.py

**Files:**
- Modify: `bin/recall-sessions.py` (show `[imported from X]` tag)

**Step 1: Find the list_sessions display function**

Read `bin/recall-sessions.py` lines 883-920 (the `list_sessions()` function).

**Step 2: Add imported session display logic**

In `list_sessions()`, where session summaries are printed, check for the `source` and `sharer` fields:

```python
# Inside the loop that prints session summaries
source = session_entry.get('source', '')
sharer = session_entry.get('sharer', '')
if source == 'import' and sharer:
    summary_prefix = f"[imported from {sharer}] "
else:
    summary_prefix = ""
# Use: f"  {summary_prefix}{summary}"
```

Apply the same pattern in `show_last_session()` and `search_sessions()`.

**Step 3: Test manually**

Create a test imported session in the index, then run:
Run: `cd ~/ashcode/recall-skill && python3 bin/recall-sessions.py "$(pwd)"`
Expected: Imported sessions show `[imported from X]` tag

**Step 4: Commit**

```bash
cd ~/ashcode/recall-skill
git add bin/recall-sessions.py
git commit -m "feat: display imported sessions with [imported from X] tag"
```

---

### Task 8: Integration Test — Full Share/Import Round Trip

**Files:**
- Create: `tests/test_share_import_roundtrip.py`

**Step 1: Write the round-trip test**

```python
# tests/test_share_import_roundtrip.py
"""End-to-end test: share a session, import the zip, verify it appears in index."""
import sys
import json
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'bin'))

from shared import load_index, save_index, get_session_details_dir
from sanitizer import Sanitizer
from recall_share import resolve_session, build_package
from recall_import import parse_zip_package, merge_into_index


class TestRoundTrip:
    def test_share_then_import(self, tmp_path):
        """Full round trip: create session data -> share -> import -> verify."""
        # Simulate session data with a secret
        session_data = {
            'session_id': 'roundtrip-test',
            'date': '2026-03-13T14:00:00',
            'summary': 'Debug auth with key sk-ant-secret123',
            'project': 'test-project',
            'user_messages': [
                {'content': 'Fix /Users/alice/code/auth.py', 'index': 0, 'timestamp': '2026-03-13T14:00:00'},
                {'content': 'Use token sk-ant-secret123', 'index': 1, 'timestamp': '2026-03-13T14:01:00'},
            ],
            'commands': [
                {'command': 'curl -u "admin:password123" https://api.test.com', 'tool_id': 'c1', 'index': 2},
            ],
            'failures': [],
            'failure_patterns': {},
            'topics': ['auth', 'API'],
            'skills_used': [],
        }

        # Step 1: Sanitize
        sanitizer = Sanitizer()
        sanitized = sanitizer.sanitize_dict(session_data)
        report = sanitizer.get_report()

        # Verify sanitization
        assert 'sk-ant-secret123' not in json.dumps(sanitized)
        assert '/Users/alice' not in json.dumps(sanitized)
        assert 'password123' not in json.dumps(sanitized)
        assert report['total_redactions'] > 0

        # Step 2: Package
        zip_path = build_package(sanitized, report, tmp_path, sharer='alice')
        assert zip_path.exists()

        # Step 3: Import
        package = parse_zip_package(zip_path)
        assert package['manifest']['sharer'] == 'alice'

        # Step 4: Merge into a fresh index
        index = {
            'version': 2,
            'sessions': {},
            'failure_patterns': {},
            'learnings': [],
            'pending_learnings': [],
            'usage': {'skills': {}, 'learnings_shown': {}},
        }
        merge_into_index(index, package['session'])

        # Verify
        assert 'imported-roundtrip-test' in index['sessions']
        entry = index['sessions']['imported-roundtrip-test']
        assert entry['source'] == 'import'
        assert entry['sharer'] == 'alice'
        assert entry['message_count'] == 2
        # Verify no secrets leaked into index
        assert 'sk-ant-secret123' not in json.dumps(index)
        assert 'password123' not in json.dumps(index)
```

**Step 2: Run the round-trip test**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/test_share_import_roundtrip.py -v`
Expected: All PASS

**Step 3: Run full test suite**

Run: `cd ~/ashcode/recall-skill && python3 -m pytest tests/ -v`
Expected: All tests pass

**Step 4: Commit**

```bash
cd ~/ashcode/recall-skill
git add tests/test_share_import_roundtrip.py
git commit -m "test: add end-to-end share/import round trip test"
```

---

## Task Summary

| Task | Description | New Files | Modified Files |
|------|-------------|-----------|----------------|
| 1 | Sanitizer core engine | `lib/sanitizer.py`, `tests/test_sanitizer.py` | — |
| 2 | Sanitizer config + custom rules | `defaults/sanitize-defaults.yml` | `tests/test_sanitizer.py` |
| 3 | Session helpers (shares dir, transcript) | `tests/test_share.py` | `lib/shared.py` |
| 4 | Share script (packager) | `bin/recall-share.py` | `tests/test_share.py` |
| 5 | Import script (zip + plain text) | `bin/recall-import.py`, `tests/test_import.py` | — |
| 6 | Command routing | — | `commands/recall.md` |
| 7 | Display imported sessions | — | `bin/recall-sessions.py` |
| 8 | Integration round-trip test | `tests/test_share_import_roundtrip.py` | — |