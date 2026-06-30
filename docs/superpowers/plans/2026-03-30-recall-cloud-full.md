# recall Cloud: Full Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a paid cloud sync service ($1.50/quarter) for recall session data, including the sync engine it plugs into, the Cloudflare Worker backend, Stripe billing, and microsite pages.

**Architecture:** The sync engine (Python) uses a provider adapter pattern — git for free self-hosted sync, cloud for our managed R2 backend. The cloud backend is a Cloudflare Worker (TypeScript) with R2 storage, KV for rate limits/auth, and Stripe for billing. The Worker is intentionally dumb: auth, rate limits, store blobs. All intelligence (YAML serialization, secret scanning, conflict-free layout) lives in the Python sync engine.

**Tech Stack:** Python 3.8+ (sync engine, existing codebase), TypeScript (Cloudflare Worker), Cloudflare R2 + KV + Workers, Stripe Checkout + Webhooks, YAML (synced file format), pytest (Python tests), vitest (Worker tests)

**Specs:**
- `docs/superpowers/specs/2026-03-30-recall-cloud-design.md` — cloud service spec
- `docs/superpowers/specs/2026-03-30-git-sync-adm-design.md` — git-sync + ADM spec

**Phases:**
1. Sync engine core (Python) — provider pattern, YAML format, secret scan, .recallignore
2. Git provider adapter — GitHub/GitLab/Bitbucket via shell git
3. Cloudflare Worker — auth, rate limiting, R2 CRUD, Stripe webhooks
4. Cloud provider adapter — HTTP client connecting sync engine to Worker
5. Plugin integration — hooks, commands, auto-sync
6. Microsite pages — cloud.html, self-host.html
7. agent-adm plugin — standalone ADM creation/review (separate repo)

**Dependency graph:**
```
Phase 1 (sync core) ──→ Phase 2 (git provider)
                    ──→ Phase 4 (cloud adapter) ──→ Phase 5 (plugin integration)
Phase 3 (Worker)   ──→ Phase 4 (cloud adapter)
                   ──→ Phase 6 (microsite)
Phase 7 (agent-adm) — independent, can parallel with anything
```

---

## Phase 1: Sync Engine Core

### Task 1: Sync config loader

**Files:**
- Create: `lib/sync_config.py`
- Create: `tests/test_sync_config.py`

- [ ] **Step 1: Write failing test for config loading**

```python
# tests/test_sync_config.py
import pytest
import json
import yaml
from pathlib import Path
from unittest.mock import patch

def test_load_sync_config_from_yaml(tmp_path):
    """Load sync config from YAML file."""
    config_file = tmp_path / "sync.yaml"
    config_file.write_text("""
sync:
  provider: cloud
  endpoint: https://recall-api.workers.dev
  api_key_file: ~/.env/recall/api-key
  tier: lite
  auto_sync: true
  include:
    restarts: true
    learnings: true
    sops: true
    adm: true
    session_metadata: true
    agent_configs: true
    transcripts: false
""")
    from lib.sync_config import load_sync_config
    config = load_sync_config(config_path=config_file)
    assert config.provider == "cloud"
    assert config.endpoint == "https://recall-api.workers.dev"
    assert config.tier == "lite"
    assert config.auto_sync is True
    assert config.include.restarts is True
    assert config.include.transcripts is False


def test_load_sync_config_missing_file():
    """Return None when config file doesn't exist."""
    from lib.sync_config import load_sync_config
    config = load_sync_config(config_path=Path("/nonexistent/sync.yaml"))
    assert config is None


def test_load_sync_config_defaults(tmp_path):
    """Missing keys get sensible defaults."""
    config_file = tmp_path / "sync.yaml"
    config_file.write_text("""
sync:
  provider: github
  repo: git@github.com:user/recall-data.git
""")
    from lib.sync_config import load_sync_config
    config = load_sync_config(config_path=config_file)
    assert config.provider == "github"
    assert config.auto_sync is True  # default
    assert config.tier == "lite"  # default
    assert config.include.restarts is True  # default
    assert config.include.transcripts is False  # default


def test_sync_config_env_override(tmp_path, monkeypatch):
    """RECALL_SYNC_REPO env var overrides config file."""
    monkeypatch.setenv("RECALL_SYNC_REPO", "git@github.com:env/repo.git")
    from lib.sync_config import load_sync_config
    config = load_sync_config(config_path=Path("/nonexistent"))
    assert config is not None
    assert config.repo == "git@github.com:env/repo.git"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/exampleuser/ashcode/recall && python3 -m pytest tests/test_sync_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.sync_config'`

- [ ] **Step 3: Implement sync config loader**

```python
# lib/sync_config.py
"""
Sync configuration loader.

Reads ~/.config/recall/sync.yaml and provides typed access
to sync settings. Supports env var override (RECALL_SYNC_REPO).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "recall" / "sync.yaml"


@dataclass
class SyncInclude:
    restarts: bool = True
    learnings: bool = True
    sops: bool = True
    adm: bool = True
    session_metadata: bool = True
    agent_configs: bool = True
    transcripts: bool = False


@dataclass
class SyncConfig:
    provider: str = "github"
    repo: Optional[str] = None
    endpoint: Optional[str] = None
    api_key_file: Optional[str] = None
    tier: str = "lite"
    auto_sync: bool = True
    mode: str = "auto"  # auto | auto-pull | manual
    secret_scan: str = "warn"  # warn | strict | off
    include: SyncInclude = field(default_factory=SyncInclude)


def load_sync_config(config_path: Path = None) -> Optional[SyncConfig]:
    """Load sync config from YAML, with env var fallback."""
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    # Env var override — minimal config from env
    env_repo = os.environ.get("RECALL_SYNC_REPO")
    if env_repo:
        return SyncConfig(
            provider=_detect_provider(env_repo),
            repo=env_repo,
        )

    if not config_path.exists():
        return None

    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f)
    except (yaml.YAMLError, IOError):
        return None

    if not raw or "sync" not in raw:
        return None

    s = raw["sync"]
    include_raw = s.get("include", {})

    return SyncConfig(
        provider=s.get("provider", "github"),
        repo=s.get("repo"),
        endpoint=s.get("endpoint"),
        api_key_file=s.get("api_key_file"),
        tier=s.get("tier", "lite"),
        auto_sync=s.get("auto_sync", True),
        mode=s.get("mode", "auto"),
        secret_scan=s.get("secret_scan", "warn"),
        include=SyncInclude(
            restarts=include_raw.get("restarts", True),
            learnings=include_raw.get("learnings", True),
            sops=include_raw.get("sops", True),
            adm=include_raw.get("adm", True),
            session_metadata=include_raw.get("session_metadata", True),
            agent_configs=include_raw.get("agent_configs", True),
            transcripts=include_raw.get("transcripts", False),
        ),
    )


def _detect_provider(repo_url: str) -> str:
    """Guess provider from repo URL."""
    if "github.com" in repo_url:
        return "github"
    if "gitlab.com" in repo_url:
        return "gitlab"
    if "bitbucket.org" in repo_url:
        return "bitbucket"
    return "github"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_sync_config.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/sync_config.py tests/test_sync_config.py
git commit -m "feat: add sync config loader with YAML parsing and env override"
```

---

### Task 2: YAML serializer for recall artifacts

**Files:**
- Create: `lib/sync_format.py`
- Create: `tests/test_sync_format.py`

- [ ] **Step 1: Write failing tests for YAML serialization**

```python
# tests/test_sync_format.py
import pytest
from datetime import datetime
from pathlib import Path

def test_restart_to_yaml():
    """Convert a restart prompt to sync YAML format."""
    from lib.sync_format import restart_to_yaml, yaml_to_restart
    restart = {
        "name": "payroll-fix",
        "date": "2026-03-20",
        "project": "myapp",
        "branch": "feature/payroll-fix",
        "summary": "Fixing payroll bonus calculation",
        "next_steps": "Fix rounding edge case on line 247",
        "content": "Full restart prompt content here...",
    }
    yaml_str = restart_to_yaml(restart)
    assert "name: payroll-fix" in yaml_str
    assert "content:" in yaml_str

    # Round-trip
    parsed = yaml_to_restart(yaml_str)
    assert parsed["name"] == "payroll-fix"
    assert parsed["content"] == "Full restart prompt content here..."


def test_learning_to_yaml():
    """Convert a learning to sync YAML format."""
    from lib.sync_format import learning_to_yaml, yaml_to_learning
    learning = {
        "bucket": "personal",
        "category": "git",
        "title": "SSH vs HTTPS remotes",
        "description": "HTTPS tokens expire; SSH keys are persistent",
        "solution": "git remote set-url origin git@github.com:org/repo.git",
    }
    yaml_str = learning_to_yaml(learning)
    parsed = yaml_to_learning(yaml_str)
    assert parsed["bucket"] == "personal"
    assert parsed["title"] == "SSH vs HTTPS remotes"


def test_session_metadata_to_yaml():
    """Convert session metadata (no raw content) to sync YAML."""
    from lib.sync_format import session_meta_to_yaml, yaml_to_session_meta
    meta = {
        "session_id": "abc123",
        "date": "2026-03-20T09:41:00",
        "project": "myapp",
        "summary": "Implementing payroll bonus fix",
        "message_count": 34,
        "command_count": 12,
        "failure_count": 2,
        "topics": ["payroll", "rounding"],
        "source_platform": "claude-code",
        "source_machine": "ashbook-pro",
    }
    yaml_str = session_meta_to_yaml(meta)
    parsed = yaml_to_session_meta(yaml_str)
    assert parsed["session_id"] == "abc123"
    assert parsed["source_platform"] == "claude-code"
    assert parsed["topics"] == ["payroll", "rounding"]


def test_sop_to_yaml():
    """Convert an SOP to sync YAML format."""
    from lib.sync_format import sop_to_yaml, yaml_to_sop
    sop = {
        "category": "git_error",
        "pattern": "permission denied on push",
        "solution": "Switch HTTPS to SSH remote",
        "commands": ["git remote set-url origin git@github.com:org/repo.git"],
    }
    yaml_str = sop_to_yaml(sop)
    parsed = yaml_to_sop(yaml_str)
    assert parsed["category"] == "git_error"


def test_agent_config_to_yaml():
    """Convert an agent config snapshot to sync YAML."""
    from lib.sync_format import agent_config_to_yaml, yaml_to_agent_config
    snapshot = {
        "file": "CLAUDE.md",
        "project": "myapp",
        "snapshot_date": "2026-03-30T08:01:00",
        "session_id": "abc123",
        "changed_by": "agent:claude-opus-4-6",
        "diff_summary": "Added 3 rules about ArangoDB",
        "content": "# CLAUDE.md\n\nRules here...",
    }
    yaml_str = agent_config_to_yaml(snapshot)
    parsed = yaml_to_agent_config(yaml_str)
    assert parsed["file"] == "CLAUDE.md"
    assert parsed["changed_by"] == "agent:claude-opus-4-6"
    assert "Rules here..." in parsed["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sync_format.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement YAML serializer**

```python
# lib/sync_format.py
"""
YAML serializers for sync artifacts.

Each artifact type has a to_yaml() and from_yaml() function.
YAML is used because it's human-readable, supports comments,
and can be inspected with cat.
"""

import yaml


def restart_to_yaml(restart: dict) -> str:
    return yaml.dump(restart, default_flow_style=False, sort_keys=False, allow_unicode=True)

def yaml_to_restart(text: str) -> dict:
    return yaml.safe_load(text)

def learning_to_yaml(learning: dict) -> str:
    return yaml.dump(learning, default_flow_style=False, sort_keys=False, allow_unicode=True)

def yaml_to_learning(text: str) -> dict:
    return yaml.safe_load(text)

def session_meta_to_yaml(meta: dict) -> str:
    return yaml.dump(meta, default_flow_style=False, sort_keys=False, allow_unicode=True)

def yaml_to_session_meta(text: str) -> dict:
    return yaml.safe_load(text)

def sop_to_yaml(sop: dict) -> str:
    return yaml.dump(sop, default_flow_style=False, sort_keys=False, allow_unicode=True)

def yaml_to_sop(text: str) -> dict:
    return yaml.safe_load(text)

def agent_config_to_yaml(snapshot: dict) -> str:
    return yaml.dump(snapshot, default_flow_style=False, sort_keys=False, allow_unicode=True)

def yaml_to_agent_config(text: str) -> dict:
    return yaml.safe_load(text)


def sync_filename(artifact_type: str, name: str, date: str) -> str:
    """Generate a conflict-free filename: YYYY-MM-DD_slug.yaml"""
    date_prefix = date[:10] if len(date) >= 10 else date
    slug = name.lower().replace(" ", "-").replace("/", "-")[:60]
    return f"{date_prefix}_{slug}.yaml"
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_sync_format.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/sync_format.py tests/test_sync_format.py
git commit -m "feat: add YAML serializers for sync artifact types"
```

---

### Task 3: Secret scanner

**Files:**
- Create: `lib/sync_scan.py`
- Create: `tests/test_sync_scan.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sync_scan.py
import pytest

def test_detects_aws_key():
    from lib.sync_scan import scan_for_secrets
    content = "aws_key: AKIAIOSFODNN7EXAMPLE"
    findings = scan_for_secrets(content)
    assert len(findings) >= 1
    assert any("AWS" in f["type"] for f in findings)


def test_detects_api_token():
    from lib.sync_scan import scan_for_secrets
    content = "token: sk-proj-abc123def456ghi789"
    findings = scan_for_secrets(content)
    assert len(findings) >= 1


def test_detects_github_token():
    from lib.sync_scan import scan_for_secrets
    content = "GITHUB_TOKEN=ghp_ABCDEFghijklmnop1234567890abcdef"
    findings = scan_for_secrets(content)
    assert len(findings) >= 1


def test_detects_connection_string():
    from lib.sync_scan import scan_for_secrets
    content = "db: postgres://user:pass@host:5432/mydb"
    findings = scan_for_secrets(content)
    assert len(findings) >= 1


def test_detects_bearer_token():
    from lib.sync_scan import scan_for_secrets
    content = 'Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9'
    findings = scan_for_secrets(content)
    assert len(findings) >= 1


def test_clean_content_passes():
    from lib.sync_scan import scan_for_secrets
    content = """
name: payroll-fix
summary: Fixed rounding in bonus calc
next_steps: Run test suite
"""
    findings = scan_for_secrets(content)
    assert len(findings) == 0


def test_scan_file(tmp_path):
    from lib.sync_scan import scan_file
    f = tmp_path / "test.yaml"
    f.write_text("secret: AKIAIOSFODNN7EXAMPLE\n")
    findings = scan_file(f)
    assert len(findings) >= 1
    assert findings[0]["file"] == str(f)


def test_scan_directory(tmp_path):
    from lib.sync_scan import scan_directory
    clean = tmp_path / "clean.yaml"
    clean.write_text("name: safe\n")
    dirty = tmp_path / "dirty.yaml"
    dirty.write_text("key: ghp_ABCDEFghijklmnop1234567890abcdef\n")
    results = scan_directory(tmp_path)
    assert len(results) == 1
    assert "dirty.yaml" in results[0]["file"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sync_scan.py -v`
Expected: FAIL

- [ ] **Step 3: Implement secret scanner**

```python
# lib/sync_scan.py
"""
Secret scanning for sync push.

Scans YAML files for common secret patterns before pushing to
a remote (git or cloud). Reuses the patterns from the existing
share/import feature.
"""

import re
from pathlib import Path
from typing import List


SECRET_PATTERNS = [
    ("AWS access key", r"AKIA[0-9A-Z]{16}"),
    ("API token (sk-)", r"sk-[a-zA-Z0-9_-]{20,}"),
    ("GitHub token", r"ghp_[a-zA-Z0-9]{36}"),
    ("GitLab token", r"glpat-[a-zA-Z0-9_-]{20,}"),
    ("Bearer token", r"Bearer\s+[a-zA-Z0-9._-]{20,}"),
    ("Connection string", r"(?:postgres|mongodb|mysql|redis)://[^\s]+:[^\s]+@"),
    ("Password field", r"(?:password|passwd|secret)\s*[=:]\s*\S{8,}"),
    ("Private key", r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"),
]

_compiled = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in SECRET_PATTERNS]


def scan_for_secrets(content: str) -> List[dict]:
    """Scan text content for secret patterns. Returns list of findings."""
    findings = []
    for line_num, line in enumerate(content.splitlines(), 1):
        for name, regex in _compiled:
            if regex.search(line):
                findings.append({
                    "type": name,
                    "line": line_num,
                    "preview": line.strip()[:80],
                })
    return findings


def scan_file(file_path: Path) -> List[dict]:
    """Scan a single file for secrets."""
    try:
        content = file_path.read_text(errors="replace")
    except IOError:
        return []
    findings = scan_for_secrets(content)
    for f in findings:
        f["file"] = str(file_path)
    return findings


def scan_directory(dir_path: Path, glob: str = "*.yaml") -> List[dict]:
    """Scan all matching files in a directory. Returns findings with file paths."""
    all_findings = []
    for f in dir_path.rglob(glob):
        all_findings.extend(scan_file(f))
    return all_findings
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_sync_scan.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/sync_scan.py tests/test_sync_scan.py
git commit -m "feat: add secret scanner for pre-push safety"
```

---

### Task 4: .recallignore parser

**Files:**
- Create: `lib/sync_ignore.py`
- Create: `tests/test_sync_ignore.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sync_ignore.py
import pytest
from pathlib import Path

def test_parse_recallignore(tmp_path):
    from lib.sync_ignore import load_ignore_patterns, should_ignore
    ignore_file = tmp_path / ".recallignore"
    ignore_file.write_text("""
# Never sync infra sessions
projects/demo-infra-*
projects/secrets-*

# Exclude specific ADMs
adm/2026-03-15_internal-auth-*.yaml
""")
    patterns = load_ignore_patterns(ignore_file)
    assert should_ignore("projects/demo-infra-prod/session.yaml", patterns)
    assert should_ignore("projects/secrets-vault/restart.yaml", patterns)
    assert should_ignore("adm/2026-03-15_internal-auth-flow.yaml", patterns)
    assert not should_ignore("restarts/payroll-fix.yaml", patterns)
    assert not should_ignore("adm/2026-03-20_postgres.yaml", patterns)


def test_empty_recallignore():
    from lib.sync_ignore import load_ignore_patterns, should_ignore
    patterns = load_ignore_patterns(Path("/nonexistent"))
    assert not should_ignore("anything.yaml", patterns)


def test_comments_and_blanks(tmp_path):
    from lib.sync_ignore import load_ignore_patterns
    ignore_file = tmp_path / ".recallignore"
    ignore_file.write_text("""
# comment

# another comment
*.tmp
""")
    patterns = load_ignore_patterns(ignore_file)
    assert len(patterns) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sync_ignore.py -v`
Expected: FAIL

- [ ] **Step 3: Implement .recallignore parser**

```python
# lib/sync_ignore.py
"""
.recallignore parser.

Follows gitignore-style patterns (fnmatch). Loaded from the sync
repo root to exclude files from push/pull.
"""

import fnmatch
from pathlib import Path
from typing import List


def load_ignore_patterns(ignore_path: Path) -> List[str]:
    """Load patterns from a .recallignore file. Returns empty list if missing."""
    if not ignore_path.exists():
        return []
    patterns = []
    for line in ignore_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def should_ignore(file_path: str, patterns: List[str]) -> bool:
    """Check if a file path matches any ignore pattern."""
    for pattern in patterns:
        if fnmatch.fnmatch(file_path, pattern):
            return True
    return False
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_sync_ignore.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/sync_ignore.py tests/test_sync_ignore.py
git commit -m "feat: add .recallignore parser for sync exclusions"
```

---

### Task 5: Sync engine with provider adapter pattern

**Files:**
- Create: `lib/sync.py`
- Create: `tests/test_sync.py`

- [ ] **Step 1: Write failing tests for the sync engine interface**

```python
# tests/test_sync.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from datetime import datetime


def test_provider_interface():
    """Provider adapters must implement push, pull, status."""
    from lib.sync import SyncProvider
    # SyncProvider is abstract — instantiating should fail
    with pytest.raises(TypeError):
        SyncProvider()


def test_gather_sync_files(tmp_path):
    """Gather files from local recall data for push."""
    from lib.sync import gather_sync_files
    from lib.sync_config import SyncConfig, SyncInclude

    # Create mock local data
    restarts = tmp_path / "restarts"
    restarts.mkdir()
    (restarts / "2026-03-20_payroll-fix.yaml").write_text("name: payroll-fix\n")
    (restarts / "2026-03-28_auth-refactor.yaml").write_text("name: auth-refactor\n")

    learnings = tmp_path / "learnings"
    learnings.mkdir()
    (learnings / "2026-03-15_git-ssh.yaml").write_text("title: SSH vs HTTPS\n")

    config = SyncConfig(include=SyncInclude(restarts=True, learnings=True))
    files = gather_sync_files(tmp_path, config)

    assert len(files) == 3
    paths = [f["relative_path"] for f in files]
    assert "restarts/2026-03-20_payroll-fix.yaml" in paths
    assert "learnings/2026-03-15_git-ssh.yaml" in paths


def test_gather_respects_include_flags(tmp_path):
    """Disabled categories are not gathered."""
    from lib.sync import gather_sync_files
    from lib.sync_config import SyncConfig, SyncInclude

    restarts = tmp_path / "restarts"
    restarts.mkdir()
    (restarts / "file.yaml").write_text("x: 1\n")

    learnings = tmp_path / "learnings"
    learnings.mkdir()
    (learnings / "file.yaml").write_text("x: 1\n")

    config = SyncConfig(include=SyncInclude(restarts=True, learnings=False))
    files = gather_sync_files(tmp_path, config)

    paths = [f["relative_path"] for f in files]
    assert any("restarts" in p for p in paths)
    assert not any("learnings" in p for p in paths)


def test_gather_respects_recallignore(tmp_path):
    """Files matching .recallignore are excluded."""
    from lib.sync import gather_sync_files
    from lib.sync_config import SyncConfig, SyncInclude

    restarts = tmp_path / "restarts"
    restarts.mkdir()
    (restarts / "safe.yaml").write_text("x: 1\n")
    (restarts / "secret-project.yaml").write_text("x: 1\n")

    ignore = tmp_path / ".recallignore"
    ignore.write_text("restarts/secret-*\n")

    config = SyncConfig(include=SyncInclude(restarts=True))
    files = gather_sync_files(tmp_path, config, ignore_path=ignore)

    paths = [f["relative_path"] for f in files]
    assert "restarts/safe.yaml" in paths
    assert "restarts/secret-project.yaml" not in paths


def test_gather_runs_secret_scan(tmp_path):
    """Files with detected secrets are flagged."""
    from lib.sync import gather_sync_files
    from lib.sync_config import SyncConfig, SyncInclude

    restarts = tmp_path / "restarts"
    restarts.mkdir()
    (restarts / "dirty.yaml").write_text("token: ghp_ABCDEFghijklmnop1234567890abcdef\n")

    config = SyncConfig(secret_scan="strict", include=SyncInclude(restarts=True))
    files = gather_sync_files(tmp_path, config)

    assert len(files) == 1
    assert files[0]["secret_findings"]  # has findings
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sync.py -v`
Expected: FAIL

- [ ] **Step 3: Implement sync engine core**

```python
# lib/sync.py
"""
Sync engine core.

Provides the provider adapter pattern and file gathering logic.
Providers (git, cloud) implement the SyncProvider interface.
"""

import abc
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict

from lib.sync_config import SyncConfig
from lib.sync_ignore import load_ignore_patterns, should_ignore
from lib.sync_scan import scan_file


# Category → subdirectory mapping
SYNC_CATEGORIES = {
    "restarts": "restarts",
    "learnings": "learnings",
    "sops": "sops",
    "adm": "adm",
    "session_metadata": "sessions",
    "agent_configs": "agent-configs",
    "transcripts": "transcripts",
}


@dataclass
class SyncFile:
    relative_path: str
    absolute_path: Path
    content: bytes
    secret_findings: List[dict]


class SyncProvider(abc.ABC):
    """Interface that all sync providers must implement."""

    @abc.abstractmethod
    def push(self, files: List[SyncFile], config: SyncConfig) -> dict:
        """Push files to remote. Returns {pushed: int, errors: list}."""

    @abc.abstractmethod
    def pull(self, since: Optional[str], config: SyncConfig) -> List[dict]:
        """Pull files changed since timestamp. Returns list of {path, content}."""

    @abc.abstractmethod
    def status(self, config: SyncConfig) -> dict:
        """Return remote status: storage, limits, etc."""


# Provider registry
_providers: Dict[str, type] = {}


def register_provider(name: str, cls: type):
    """Register a sync provider class."""
    _providers[name] = cls


def get_provider(name: str) -> type:
    """Get a registered provider class by name."""
    if name not in _providers:
        raise ValueError(f"Unknown sync provider: {name}. Available: {list(_providers.keys())}")
    return _providers[name]


def gather_sync_files(
    data_dir: Path,
    config: SyncConfig,
    ignore_path: Path = None,
) -> List[dict]:
    """Gather local files eligible for sync based on config."""
    if ignore_path is None:
        ignore_path = data_dir / ".recallignore"
    patterns = load_ignore_patterns(ignore_path)

    files = []
    include = config.include

    for category, subdir in SYNC_CATEGORIES.items():
        if not getattr(include, category, False):
            continue

        category_dir = data_dir / subdir
        if not category_dir.exists():
            continue

        for file_path in category_dir.rglob("*.yaml"):
            relative = f"{subdir}/{file_path.name}"

            if should_ignore(relative, patterns):
                continue

            findings = scan_file(file_path) if config.secret_scan != "off" else []

            files.append({
                "relative_path": relative,
                "absolute_path": file_path,
                "content": file_path.read_bytes(),
                "secret_findings": findings,
            })

    return files
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_sync.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/sync.py tests/test_sync.py
git commit -m "feat: add sync engine core with provider adapter pattern"
```

---

## Phase 2: Git Provider Adapter

### Task 6: Git provider — init and push

**Files:**
- Create: `lib/sync_git.py`
- Create: `tests/test_sync_git.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sync_git.py
import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

def _init_bare_repo(path: Path) -> str:
    """Create a bare git repo for testing."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(path)], capture_output=True)
    return str(path)


def test_git_provider_init(tmp_path):
    """Init creates a local clone of the sync repo."""
    from lib.sync_git import GitProvider
    from lib.sync_config import SyncConfig

    bare = _init_bare_repo(tmp_path / "remote.git")
    local = tmp_path / "local"
    config = SyncConfig(provider="github", repo=bare)

    provider = GitProvider(local_dir=local)
    provider.init(config)

    assert (local / ".git").exists()


def test_git_provider_push(tmp_path):
    """Push writes files to the git repo and commits."""
    from lib.sync_git import GitProvider
    from lib.sync_config import SyncConfig

    bare = _init_bare_repo(tmp_path / "remote.git")
    local = tmp_path / "local"
    config = SyncConfig(provider="github", repo=bare)

    provider = GitProvider(local_dir=local)
    provider.init(config)

    # Create a file to push
    files = [{
        "relative_path": "restarts/test.yaml",
        "absolute_path": None,
        "content": b"name: test\n",
        "secret_findings": [],
    }]
    result = provider.push(files, config)
    assert result["pushed"] == 1
    assert result["errors"] == []

    # Verify file exists in the local clone
    assert (local / "restarts" / "test.yaml").exists()


def test_git_provider_pull(tmp_path):
    """Pull retrieves files from remote."""
    from lib.sync_git import GitProvider
    from lib.sync_config import SyncConfig

    bare = _init_bare_repo(tmp_path / "remote.git")
    config = SyncConfig(provider="github", repo=bare)

    # Push from clone A
    clone_a = tmp_path / "clone_a"
    provider_a = GitProvider(local_dir=clone_a)
    provider_a.init(config)
    files = [{
        "relative_path": "restarts/from_a.yaml",
        "absolute_path": None,
        "content": b"name: from_a\n",
        "secret_findings": [],
    }]
    provider_a.push(files, config)

    # Pull from clone B
    clone_b = tmp_path / "clone_b"
    provider_b = GitProvider(local_dir=clone_b)
    provider_b.init(config)
    pulled = provider_b.pull(since=None, config=config)

    assert len(pulled) >= 1
    paths = [p["path"] for p in pulled]
    assert "restarts/from_a.yaml" in paths
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sync_git.py -v`
Expected: FAIL

- [ ] **Step 3: Implement git provider**

```python
# lib/sync_git.py
"""
Git sync provider.

Implements SyncProvider for GitHub, GitLab, and Bitbucket
using shell git commands. The repo is cloned locally; push/pull
are git add+commit+push and git pull+read.
"""

import subprocess
from pathlib import Path
from typing import List, Optional

from lib.sync import SyncProvider, register_provider
from lib.sync_config import SyncConfig


class GitProvider(SyncProvider):
    def __init__(self, local_dir: Path = None):
        if local_dir is None:
            local_dir = Path.home() / ".local" / "share" / "recall" / "sync"
        self.local_dir = local_dir

    def init(self, config: SyncConfig):
        """Clone the repo if not already cloned."""
        if (self.local_dir / ".git").exists():
            return
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self._git("clone", config.repo, str(self.local_dir))

    def push(self, files: List[dict], config: SyncConfig) -> dict:
        """Write files to local clone, commit, and push."""
        pushed = 0
        errors = []

        for f in files:
            try:
                dest = self.local_dir / f["relative_path"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(f["content"])
                self._git_in_repo("add", f["relative_path"])
                pushed += 1
            except Exception as e:
                errors.append({"file": f["relative_path"], "error": str(e)})

        if pushed > 0:
            self._git_in_repo("commit", "-m", f"sync: push {pushed} files")
            try:
                self._git_in_repo("push", "origin", "main")
            except subprocess.CalledProcessError:
                # Try master if main doesn't exist
                try:
                    self._git_in_repo("push", "origin", "master")
                except subprocess.CalledProcessError as e:
                    errors.append({"file": "push", "error": str(e)})

        return {"pushed": pushed, "errors": errors}

    def pull(self, since: Optional[str], config: SyncConfig) -> List[dict]:
        """Pull from remote and return list of files."""
        self._git_in_repo("pull", "--ff-only")

        files = []
        for yaml_file in self.local_dir.rglob("*.yaml"):
            relative = str(yaml_file.relative_to(self.local_dir))
            if relative.startswith("."):
                continue
            files.append({
                "path": relative,
                "content": yaml_file.read_bytes(),
            })
        return files

    def status(self, config: SyncConfig) -> dict:
        """Return basic status."""
        return {
            "provider": "git",
            "local_dir": str(self.local_dir),
            "initialized": (self.local_dir / ".git").exists(),
        }

    def _git(self, *args):
        subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, check=True, timeout=30,
        )

    def _git_in_repo(self, *args):
        subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, check=True, timeout=30,
            cwd=str(self.local_dir),
        )


# Register providers for all git-based remotes
register_provider("github", GitProvider)
register_provider("gitlab", GitProvider)
register_provider("bitbucket", GitProvider)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_sync_git.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/sync_git.py tests/test_sync_git.py
git commit -m "feat: add git sync provider for GitHub/GitLab/Bitbucket"
```

---

## Phase 3: Cloudflare Worker

### Task 7: Worker project scaffolding

**Files:**
- Create: `worker/package.json`
- Create: `worker/tsconfig.json`
- Create: `worker/wrangler.toml`
- Create: `worker/src/index.ts`

- [ ] **Step 1: Create worker directory and config files**

```bash
mkdir -p worker/src
```

```json
// worker/package.json
{
  "name": "recall-cloud",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "wrangler dev",
    "deploy": "wrangler deploy",
    "test": "vitest"
  },
  "devDependencies": {
    "@cloudflare/workers-types": "^4.20240512.0",
    "typescript": "^5.4.0",
    "vitest": "^1.6.0",
    "wrangler": "^3.57.0"
  },
  "dependencies": {
    "stripe": "^15.0.0"
  }
}
```

```json
// worker/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "moduleResolution": "bundler",
    "lib": ["ES2022"],
    "types": ["@cloudflare/workers-types"],
    "strict": true,
    "outDir": "dist",
    "rootDir": "src"
  },
  "include": ["src/**/*.ts"]
}
```

```toml
# worker/wrangler.toml
name = "recall-cloud"
main = "src/index.ts"
compatibility_date = "2024-05-12"

[[r2_buckets]]
binding = "BUCKET"
bucket_name = "recall-store"

[[kv_namespaces]]
binding = "KV"
id = "placeholder-replace-after-creation"
```

- [ ] **Step 2: Create the router entrypoint**

```typescript
// worker/src/index.ts
export interface Env {
  BUCKET: R2Bucket;
  KV: KVNamespace;
  STRIPE_SECRET_KEY: string;
  STRIPE_WEBHOOK_SECRET: string;
  API_KEY_SALT: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // Stripe webhook — no auth required (verified by signature)
    if (path === "/v1/webhook/stripe" && request.method === "POST") {
      const { handleStripeWebhook } = await import("./stripe");
      return handleStripeWebhook(request, env);
    }

    // All other routes require auth
    const { authenticate } = await import("./auth");
    const authResult = await authenticate(request, env);
    if (!authResult.ok) {
      return new Response(JSON.stringify({ error: authResult.error }), {
        status: authResult.status,
        headers: { "Content-Type": "application/json" },
      });
    }
    const userId = authResult.userId;

    // Rate limit check
    const { checkRateLimit } = await import("./rate-limiter");
    const rateResult = await checkRateLimit(userId, request, env);
    if (!rateResult.ok) {
      return new Response(JSON.stringify({
        error: "rate_limited",
        window: rateResult.window,
        resets_in: rateResult.resetsIn,
      }), {
        status: 429,
        headers: { "Content-Type": "application/json" },
      });
    }

    // Route to handlers
    const { handleFiles } = await import("./files");
    const { handleExport } = await import("./export");

    if (path.startsWith("/v1/files")) {
      return handleFiles(request, url, userId, env);
    }
    if (path === "/v1/status") {
      const { handleStatus } = await import("./status");
      return handleStatus(userId, env);
    }
    if (path === "/v1/export") {
      return handleExport(userId, env);
    }
    if (path === "/v1/auth/rotate" && request.method === "POST") {
      const { handleRotateKey } = await import("./auth");
      return handleRotateKey(userId, env);
    }

    return new Response(JSON.stringify({ error: "not_found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  },
};
```

- [ ] **Step 3: Install dependencies**

Run: `cd worker && npm install`
Expected: Clean install

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd worker && npx tsc --noEmit`
Expected: May have errors for unimplemented imports — that's expected. We'll build them in the next tasks.

- [ ] **Step 5: Commit**

```bash
git add worker/package.json worker/tsconfig.json worker/wrangler.toml worker/src/index.ts
git commit -m "feat: scaffold Cloudflare Worker project with router"
```

---

### Task 8: Auth middleware

**Files:**
- Create: `worker/src/auth.ts`
- Create: `worker/src/__tests__/auth.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
// worker/src/__tests__/auth.test.ts
import { describe, it, expect, vi } from "vitest";
import { authenticate, hashApiKey } from "../auth";

function mockEnv(kvStore: Record<string, string> = {}) {
  return {
    BUCKET: {} as any,
    KV: {
      get: vi.fn(async (key: string) => kvStore[key] ?? null),
      put: vi.fn(),
      delete: vi.fn(),
    } as any,
    STRIPE_SECRET_KEY: "sk_test_123",
    STRIPE_WEBHOOK_SECRET: "whsec_123",
    API_KEY_SALT: "test-salt-value",
  };
}

describe("authenticate", () => {
  it("rejects missing Authorization header", async () => {
    const req = new Request("https://api.test/v1/files", {});
    const result = await authenticate(req, mockEnv());
    expect(result.ok).toBe(false);
    expect(result.status).toBe(401);
  });

  it("rejects invalid API key", async () => {
    const req = new Request("https://api.test/v1/files", {
      headers: { Authorization: "Bearer sk_recall_invalid" },
    });
    const result = await authenticate(req, mockEnv());
    expect(result.ok).toBe(false);
    expect(result.status).toBe(401);
  });

  it("accepts valid API key", async () => {
    const rawKey = "sk_recall_abc123def456";
    const hash = await hashApiKey(rawKey, "test-salt-value");
    const kvStore = {
      [`key:${hash}`]: JSON.stringify({
        user_id: "user_001",
        email: "test@example.com",
        tier: "lite",
        status: "active",
      }),
    };
    const req = new Request("https://api.test/v1/files", {
      headers: { Authorization: `Bearer ${rawKey}` },
    });
    const result = await authenticate(req, mockEnv(kvStore));
    expect(result.ok).toBe(true);
    expect(result.userId).toBe("user_001");
  });

  it("rejects expired account", async () => {
    const rawKey = "sk_recall_abc123def456";
    const hash = await hashApiKey(rawKey, "test-salt-value");
    const kvStore = {
      [`key:${hash}`]: JSON.stringify({
        user_id: "user_001",
        status: "expired",
      }),
    };
    const req = new Request("https://api.test/v1/files", {
      headers: { Authorization: `Bearer ${rawKey}` },
    });
    const result = await authenticate(req, mockEnv(kvStore));
    expect(result.ok).toBe(false);
    expect(result.status).toBe(403);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd worker && npx vitest run src/__tests__/auth.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Implement auth module**

```typescript
// worker/src/auth.ts
import type { Env } from "./index";

interface AuthSuccess {
  ok: true;
  userId: string;
  tier: string;
}

interface AuthFailure {
  ok: false;
  status: number;
  error: string;
}

type AuthResult = AuthSuccess | AuthFailure;

export async function hashApiKey(rawKey: string, salt: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(rawKey + salt);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function authenticate(request: Request, env: Env): Promise<AuthResult> {
  const authHeader = request.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) {
    return { ok: false, status: 401, error: "missing_api_key" };
  }

  const rawKey = authHeader.slice(7);
  const keyHash = await hashApiKey(rawKey, env.API_KEY_SALT);
  const record = await env.KV.get(`key:${keyHash}`);

  if (!record) {
    return { ok: false, status: 401, error: "invalid_api_key" };
  }

  const data = JSON.parse(record);

  if (data.status === "expired" || data.status === "deleted") {
    return { ok: false, status: 403, error: `account_${data.status}` };
  }
  if (data.status === "inactive") {
    return { ok: false, status: 403, error: "account_inactive" };
  }

  return { ok: true, userId: data.user_id, tier: data.tier || "lite" };
}

export async function handleRotateKey(userId: string, env: Env): Promise<Response> {
  // Generate new key
  const rawBytes = new Uint8Array(32);
  crypto.getRandomValues(rawBytes);
  const newRawKey = "sk_recall_" + Array.from(rawBytes).map(b => b.toString(16).padStart(2, "0")).join("");
  const newHash = await hashApiKey(newRawKey, env.API_KEY_SALT);

  // Find and delete old key (by iterating — KV list with prefix)
  const oldKeys = await env.KV.list({ prefix: `key:` });
  for (const key of oldKeys.keys) {
    const val = await env.KV.get(key.name);
    if (val) {
      const data = JSON.parse(val);
      if (data.user_id === userId) {
        // Copy data to new key, delete old
        await env.KV.put(`key:${newHash}`, JSON.stringify(data));
        await env.KV.delete(key.name);
        break;
      }
    }
  }

  return new Response(JSON.stringify({ api_key: newRawKey }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
```

- [ ] **Step 4: Run tests**

Run: `cd worker && npx vitest run src/__tests__/auth.test.ts`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add worker/src/auth.ts worker/src/__tests__/auth.test.ts
git commit -m "feat: add Worker auth middleware with API key hashing"
```

---

### Task 9: Rate limiter (5-window)

**Files:**
- Create: `worker/src/rate-limiter.ts`
- Create: `worker/src/__tests__/rate-limiter.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
// worker/src/__tests__/rate-limiter.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { checkRateLimit, LIMITS } from "../rate-limiter";

function mockEnv(kvStore: Record<string, string> = {}) {
  return {
    BUCKET: {} as any,
    KV: {
      get: vi.fn(async (key: string) => kvStore[key] ?? null),
      put: vi.fn(),
    } as any,
    STRIPE_SECRET_KEY: "",
    STRIPE_WEBHOOK_SECRET: "",
    API_KEY_SALT: "",
  };
}

describe("checkRateLimit", () => {
  it("allows request when under all limits", async () => {
    const req = new Request("https://api.test/v1/files/test.yaml");
    const result = await checkRateLimit("user_001", req, mockEnv());
    expect(result.ok).toBe(true);
  });

  it("blocks request when hourly limit exceeded", async () => {
    const now = new Date();
    const hourKey = `rate:user_001:hour:${now.toISOString().slice(0, 13)}`;
    const kvStore = {
      [hourKey]: JSON.stringify({ req: LIMITS.hourly.maxRequests + 1, in: 0, out: 0 }),
    };
    const req = new Request("https://api.test/v1/files/test.yaml");
    const result = await checkRateLimit("user_001", req, mockEnv(kvStore));
    expect(result.ok).toBe(false);
    expect(result.window).toBe("hourly");
  });

  it("blocks request when daily limit exceeded", async () => {
    const now = new Date();
    const dayKey = `rate:user_001:day:${now.toISOString().slice(0, 10)}`;
    const kvStore = {
      [dayKey]: JSON.stringify({ req: LIMITS.daily.maxRequests + 1, in: 0, out: 0 }),
    };
    const req = new Request("https://api.test/v1/files/test.yaml");
    const result = await checkRateLimit("user_001", req, mockEnv(kvStore));
    expect(result.ok).toBe(false);
    expect(result.window).toBe("daily");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd worker && npx vitest run src/__tests__/rate-limiter.test.ts`
Expected: FAIL

- [ ] **Step 3: Implement rate limiter**

```typescript
// worker/src/rate-limiter.ts
import type { Env } from "./index";

interface RateOk { ok: true }
interface RateBlocked { ok: false; window: string; resetsIn: string }
type RateResult = RateOk | RateBlocked;

export const LIMITS = {
  hourly:  { maxRequests: 30,  maxBytesIn: 10_000_000,  maxBytesOut: 30_000_000,  ttl: 3600 },
  daily:   { maxRequests: 200, maxBytesIn: 50_000_000,  maxBytesOut: 100_000_000, ttl: 86400 },
  weekly:  { maxRequests: 800, maxBytesIn: 200_000_000, maxBytesOut: 500_000_000, ttl: 604800 },
  monthly: { maxRequests: 2000, maxBytesIn: 500_000_000, maxBytesOut: 1_000_000_000, ttl: 2678400 },
} as const;

type WindowName = keyof typeof LIMITS;

function windowKey(userId: string, window: WindowName): string {
  const now = new Date();
  switch (window) {
    case "hourly":  return `rate:${userId}:hour:${now.toISOString().slice(0, 13)}`;
    case "daily":   return `rate:${userId}:day:${now.toISOString().slice(0, 10)}`;
    case "weekly": {
      const jan1 = new Date(now.getFullYear(), 0, 1);
      const week = Math.ceil(((now.getTime() - jan1.getTime()) / 86400000 + jan1.getDay() + 1) / 7);
      return `rate:${userId}:week:${now.getFullYear()}-W${String(week).padStart(2, "0")}`;
    }
    case "monthly": return `rate:${userId}:month:${now.toISOString().slice(0, 7)}`;
  }
}

function timeUntilReset(window: WindowName): string {
  const now = new Date();
  let reset: Date;
  switch (window) {
    case "hourly":
      reset = new Date(now);
      reset.setMinutes(60, 0, 0);
      break;
    case "daily":
      reset = new Date(now);
      reset.setDate(reset.getDate() + 1);
      reset.setHours(0, 0, 0, 0);
      break;
    case "weekly":
      reset = new Date(now);
      reset.setDate(reset.getDate() + (7 - reset.getDay()));
      reset.setHours(0, 0, 0, 0);
      break;
    case "monthly":
      reset = new Date(now.getFullYear(), now.getMonth() + 1, 1);
      break;
  }
  const diffMs = reset.getTime() - now.getTime();
  const hours = Math.floor(diffMs / 3600000);
  const minutes = Math.floor((diffMs % 3600000) / 60000);
  if (hours > 24) return `${Math.floor(hours / 24)}d ${hours % 24}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export async function checkRateLimit(userId: string, request: Request, env: Env): Promise<RateResult> {
  for (const [window, limits] of Object.entries(LIMITS) as [WindowName, typeof LIMITS[WindowName]][]) {
    const key = windowKey(userId, window);
    const raw = await env.KV.get(key);
    if (!raw) continue;

    const counters = JSON.parse(raw);
    if (counters.req > limits.maxRequests) {
      return { ok: false, window, resetsIn: timeUntilReset(window) };
    }
  }
  return { ok: true };
}

export async function incrementCounters(userId: string, bytesIn: number, bytesOut: number, env: Env): Promise<void> {
  for (const [window, limits] of Object.entries(LIMITS) as [WindowName, typeof LIMITS[WindowName]][]) {
    const key = windowKey(userId, window);
    const raw = await env.KV.get(key);
    const counters = raw ? JSON.parse(raw) : { req: 0, in: 0, out: 0 };

    counters.req += 1;
    counters.in += bytesIn;
    counters.out += bytesOut;

    await env.KV.put(key, JSON.stringify(counters), { expirationTtl: limits.ttl });
  }
}
```

- [ ] **Step 4: Run tests**

Run: `cd worker && npx vitest run src/__tests__/rate-limiter.test.ts`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add worker/src/rate-limiter.ts worker/src/__tests__/rate-limiter.test.ts
git commit -m "feat: add 5-window rate limiter for cost protection"
```

---

### Task 10: R2 file operations

**Files:**
- Create: `worker/src/files.ts`

- [ ] **Step 1: Implement R2 CRUD handler**

```typescript
// worker/src/files.ts
import type { Env } from "./index";
import { incrementCounters } from "./rate-limiter";

export async function handleFiles(request: Request, url: URL, userId: string, env: Env): Promise<Response> {
  // Strip /v1/files/ prefix to get the file path
  const filePath = url.pathname.replace(/^\/v1\/files\/?/, "");
  const fullKey = `${userId}/${filePath}`;

  switch (request.method) {
    case "PUT":
      return putFile(fullKey, userId, request, env);
    case "GET":
      if (!filePath) return listFiles(userId, url, env);
      if (filePath.endsWith("/versions")) return listVersions(fullKey.replace(/\/versions$/, ""), env);
      return getFile(fullKey, url, env);
    case "DELETE":
      if (filePath.endsWith("/versions")) return trimVersions(fullKey.replace(/\/versions$/, ""), url, env);
      return deleteFile(fullKey, env);
    default:
      return jsonResponse({ error: "method_not_allowed" }, 405);
  }
}

async function putFile(key: string, userId: string, request: Request, env: Env): Promise<Response> {
  const body = await request.arrayBuffer();

  // Check storage cap (10GB)
  const usage = await getStorageUsed(userId, env);
  if (usage + body.byteLength > 10 * 1024 * 1024 * 1024) {
    return jsonResponse({ error: "storage_full", used: usage, cap: 10 * 1024 * 1024 * 1024 }, 507);
  }

  await env.BUCKET.put(key, body, {
    customMetadata: {
      uploaded: new Date().toISOString(),
      size: String(body.byteLength),
    },
  });

  await incrementCounters(userId, body.byteLength, 0, env);

  return jsonResponse({ ok: true, key, size: body.byteLength }, 200);
}

async function getFile(key: string, url: URL, env: Env): Promise<Response> {
  const object = await env.BUCKET.get(key);
  if (!object) {
    return jsonResponse({ error: "not_found" }, 404);
  }

  const body = await object.arrayBuffer();
  return new Response(body, {
    headers: {
      "Content-Type": "application/x-yaml",
      "X-Version": object.version || "1",
      "X-Uploaded": object.customMetadata?.uploaded || "",
    },
  });
}

async function listFiles(userId: string, url: URL, env: Env): Promise<Response> {
  const after = url.searchParams.get("after");
  const listed = await env.BUCKET.list({ prefix: `${userId}/` });

  let files = listed.objects.map((obj) => ({
    path: obj.key.replace(`${userId}/`, ""),
    size: obj.size,
    uploaded: obj.uploaded.toISOString(),
  }));

  if (after) {
    const afterDate = new Date(after);
    files = files.filter((f) => new Date(f.uploaded) > afterDate);
  }

  return jsonResponse({ files, count: files.length });
}

async function listVersions(key: string, env: Env): Promise<Response> {
  // R2 versioning: list versions of a specific object
  // Note: R2 versioning API may vary — this is the expected shape
  const versions = await env.BUCKET.list({ prefix: key, include: ["customMetadata"] });
  return jsonResponse({
    versions: versions.objects.map((v) => ({
      version: v.version,
      size: v.size,
      uploaded: v.uploaded.toISOString(),
    })),
  });
}

async function trimVersions(key: string, url: URL, env: Env): Promise<Response> {
  const keep = parseInt(url.searchParams.get("keep") || "3", 10);
  // List all versions and delete all but the newest `keep`
  const versions = await env.BUCKET.list({ prefix: key });
  const sorted = versions.objects.sort((a, b) => b.uploaded.getTime() - a.uploaded.getTime());
  let deleted = 0;

  for (const obj of sorted.slice(keep)) {
    await env.BUCKET.delete(obj.key);
    deleted++;
  }

  return jsonResponse({ ok: true, kept: keep, deleted });
}

async function deleteFile(key: string, env: Env): Promise<Response> {
  await env.BUCKET.delete(key);
  return jsonResponse({ ok: true });
}

async function getStorageUsed(userId: string, env: Env): Promise<number> {
  const listed = await env.BUCKET.list({ prefix: `${userId}/` });
  return listed.objects.reduce((sum, obj) => sum + obj.size, 0);
}

function jsonResponse(data: any, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add worker/src/files.ts
git commit -m "feat: add R2 file CRUD operations (put, get, list, delete, versions)"
```

---

### Task 11: Stripe webhook handler

**Files:**
- Create: `worker/src/stripe.ts`

- [ ] **Step 1: Implement Stripe webhook handler**

```typescript
// worker/src/stripe.ts
import type { Env } from "./index";
import { hashApiKey } from "./auth";

export async function handleStripeWebhook(request: Request, env: Env): Promise<Response> {
  const body = await request.text();
  const sig = request.headers.get("stripe-signature");

  if (!sig) {
    return jsonResponse({ error: "missing_signature" }, 400);
  }

  // Verify webhook signature
  // In production, use Stripe SDK's constructEvent. For Workers,
  // we verify manually using the webhook secret.
  let event: any;
  try {
    event = JSON.parse(body);
  } catch {
    return jsonResponse({ error: "invalid_json" }, 400);
  }

  // TODO: In production, verify sig against STRIPE_WEBHOOK_SECRET
  // using crypto.subtle. For now, trust if secret header is present.

  switch (event.type) {
    case "checkout.session.completed":
      return handleCheckoutCompleted(event.data.object, env);
    case "invoice.paid":
      return handleInvoicePaid(event.data.object, env);
    case "invoice.upcoming":
      return handleInvoiceUpcoming(event.data.object, env);
    case "customer.subscription.deleted":
      return handleSubscriptionDeleted(event.data.object, env);
    default:
      return jsonResponse({ ok: true, ignored: event.type });
  }
}

async function handleCheckoutCompleted(session: any, env: Env): Promise<Response> {
  const customerId = session.customer;
  const email = session.customer_email || session.customer_details?.email;

  // Generate API key
  const rawBytes = new Uint8Array(32);
  crypto.getRandomValues(rawBytes);
  const rawKey = "sk_recall_" + Array.from(rawBytes).map(b => b.toString(16).padStart(2, "0")).join("");
  const keyHash = await hashApiKey(rawKey, env.API_KEY_SALT);

  const userId = `user_${customerId}`;

  // Store key → user mapping
  await env.KV.put(`key:${keyHash}`, JSON.stringify({
    user_id: userId,
    email,
    tier: "lite",
    status: "active",
    stripe_customer_id: customerId,
    created: new Date().toISOString(),
  }));

  // Store user → metadata mapping
  await env.KV.put(`user:${userId}`, JSON.stringify({
    stripe_customer_id: customerId,
    email,
    status: "active",
    api_key_hash: keyHash,
    created: new Date().toISOString(),
  }));

  // Store the raw key temporarily for the success page to retrieve
  // Expires in 10 minutes — user must copy it immediately
  await env.KV.put(`pending_key:${session.id}`, rawKey, { expirationTtl: 600 });

  return jsonResponse({ ok: true, user_id: userId });
}

async function handleInvoicePaid(invoice: any, env: Env): Promise<Response> {
  const customerId = invoice.customer;
  const userId = `user_${customerId}`;
  const userRaw = await env.KV.get(`user:${userId}`);

  if (userRaw) {
    const user = JSON.parse(userRaw);
    user.status = "active";
    user.last_paid = new Date().toISOString();
    await env.KV.put(`user:${userId}`, JSON.stringify(user));

    // Also update the key record
    if (user.api_key_hash) {
      const keyRaw = await env.KV.get(`key:${user.api_key_hash}`);
      if (keyRaw) {
        const keyData = JSON.parse(keyRaw);
        keyData.status = "active";
        await env.KV.put(`key:${user.api_key_hash}`, JSON.stringify(keyData));
      }
    }
  }

  return jsonResponse({ ok: true });
}

async function handleInvoiceUpcoming(invoice: any, env: Env): Promise<Response> {
  const customerId = invoice.customer;
  const userId = `user_${customerId}`;

  // Check if user has been active in last 60 days
  const now = new Date();
  const sixtyDaysAgo = new Date(now.getTime() - 60 * 24 * 3600 * 1000);

  // Check monthly rate counter for recent activity
  const monthKey = `rate:${userId}:month:${now.toISOString().slice(0, 7)}`;
  const lastMonthKey = `rate:${userId}:month:${new Date(now.getFullYear(), now.getMonth() - 1, 1).toISOString().slice(0, 7)}`;

  const current = await env.KV.get(monthKey);
  const previous = await env.KV.get(lastMonthKey);

  const hasActivity = (current && JSON.parse(current).req > 0) ||
                      (previous && JSON.parse(previous).req > 0);

  if (!hasActivity) {
    // Cancel subscription — would call Stripe API here
    // For now, mark as inactive
    const userRaw = await env.KV.get(`user:${userId}`);
    if (userRaw) {
      const user = JSON.parse(userRaw);
      user.status = "inactive";
      user.inactive_since = now.toISOString();
      await env.KV.put(`user:${userId}`, JSON.stringify(user));
    }
  }

  return jsonResponse({ ok: true, active: hasActivity });
}

async function handleSubscriptionDeleted(subscription: any, env: Env): Promise<Response> {
  const customerId = subscription.customer;
  const userId = `user_${customerId}`;

  const userRaw = await env.KV.get(`user:${userId}`);
  if (userRaw) {
    const user = JSON.parse(userRaw);
    user.status = "inactive";
    user.cancelled_at = new Date().toISOString();
    await env.KV.put(`user:${userId}`, JSON.stringify(user));

    if (user.api_key_hash) {
      const keyRaw = await env.KV.get(`key:${user.api_key_hash}`);
      if (keyRaw) {
        const keyData = JSON.parse(keyRaw);
        keyData.status = "inactive";
        await env.KV.put(`key:${user.api_key_hash}`, JSON.stringify(keyData));
      }
    }
  }

  return jsonResponse({ ok: true });
}

function jsonResponse(data: any, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add worker/src/stripe.ts
git commit -m "feat: add Stripe webhook handler for billing lifecycle"
```

---

### Task 12: Status and export endpoints

**Files:**
- Create: `worker/src/status.ts`
- Create: `worker/src/export.ts`

- [ ] **Step 1: Implement status endpoint**

```typescript
// worker/src/status.ts
import type { Env } from "./index";
import { LIMITS } from "./rate-limiter";

export async function handleStatus(userId: string, env: Env): Promise<Response> {
  // Get storage usage
  const listed = await env.BUCKET.list({ prefix: `${userId}/` });
  const usedBytes = listed.objects.reduce((sum, obj) => sum + obj.size, 0);

  // Get rate limit counters
  const now = new Date();
  const limits: Record<string, any> = {};

  const windows: { name: string; key: string }[] = [
    { name: "hourly", key: `rate:${userId}:hour:${now.toISOString().slice(0, 13)}` },
    { name: "daily", key: `rate:${userId}:day:${now.toISOString().slice(0, 10)}` },
    { name: "monthly", key: `rate:${userId}:month:${now.toISOString().slice(0, 7)}` },
  ];

  for (const w of windows) {
    const raw = await env.KV.get(w.key);
    const counters = raw ? JSON.parse(raw) : { req: 0, in: 0, out: 0 };
    const max = LIMITS[w.name as keyof typeof LIMITS];
    limits[w.name] = {
      requests: counters.req,
      max_requests: max.maxRequests,
      bytes_in: counters.in,
      bytes_out: counters.out,
    };
  }

  // Get user metadata
  const userRaw = await env.KV.get(`user:${userId}`);
  const user = userRaw ? JSON.parse(userRaw) : {};

  return new Response(JSON.stringify({
    storage: { used_bytes: usedBytes, cap_bytes: 10 * 1024 * 1024 * 1024 },
    limits,
    tier: user.tier || "lite",
    billing: {
      status: user.status || "unknown",
      last_paid: user.last_paid || null,
    },
  }), {
    headers: { "Content-Type": "application/json" },
  });
}
```

```typescript
// worker/src/export.ts
import type { Env } from "./index";

export async function handleExport(userId: string, env: Env): Promise<Response> {
  // Check daily export limit (1/day)
  const now = new Date();
  const exportKey = `export:${userId}:${now.toISOString().slice(0, 10)}`;
  const exported = await env.KV.get(exportKey);

  if (exported) {
    return new Response(JSON.stringify({ error: "export_limit", message: "1 export per day" }), {
      status: 429,
      headers: { "Content-Type": "application/json" },
    });
  }

  // List all files for this user
  const listed = await env.BUCKET.list({ prefix: `${userId}/` });
  const files = listed.objects.map((obj) => ({
    path: obj.key.replace(`${userId}/`, ""),
    size: obj.size,
    uploaded: obj.uploaded.toISOString(),
  }));

  // Mark export as used for today
  await env.KV.put(exportKey, "1", { expirationTtl: 86400 });

  // Return file listing — client downloads each file individually
  // (A true tarball would require streaming, which is complex in Workers)
  return new Response(JSON.stringify({
    export: true,
    files,
    count: files.length,
    total_bytes: files.reduce((sum, f) => sum + f.size, 0),
    message: "Use /v1/files/{path} to download each file",
  }), {
    headers: { "Content-Type": "application/json" },
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add worker/src/status.ts worker/src/export.ts
git commit -m "feat: add status and export endpoints"
```

---

## Phase 4: Cloud Provider Adapter

### Task 13: Cloud provider adapter (Python)

**Files:**
- Create: `lib/sync_cloud.py`
- Create: `tests/test_sync_cloud.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sync_cloud.py
import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_cloud_provider_push(tmp_path):
    """Cloud provider PUTs each file to the Worker API."""
    from lib.sync_cloud import CloudProvider
    from lib.sync_config import SyncConfig

    config = SyncConfig(
        provider="cloud",
        endpoint="https://recall-api.workers.dev",
        api_key_file=str(tmp_path / "key"),
    )
    (tmp_path / "key").write_text("sk_recall_test123")

    provider = CloudProvider()

    files = [{
        "relative_path": "restarts/test.yaml",
        "content": b"name: test\n",
        "secret_findings": [],
    }]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True}

    with patch("lib.sync_cloud._http_request", return_value=mock_response) as mock_req:
        result = provider.push(files, config)

    assert result["pushed"] == 1
    mock_req.assert_called_once()
    call_args = mock_req.call_args
    assert call_args[0][0] == "PUT"
    assert "restarts/test.yaml" in call_args[0][1]


def test_cloud_provider_pull(tmp_path):
    """Cloud provider GETs files changed since timestamp."""
    from lib.sync_cloud import CloudProvider
    from lib.sync_config import SyncConfig

    config = SyncConfig(
        provider="cloud",
        endpoint="https://recall-api.workers.dev",
        api_key_file=str(tmp_path / "key"),
    )
    (tmp_path / "key").write_text("sk_recall_test123")

    provider = CloudProvider()

    list_response = MagicMock()
    list_response.status_code = 200
    list_response.json.return_value = {
        "files": [{"path": "restarts/test.yaml", "size": 15}],
    }

    get_response = MagicMock()
    get_response.status_code = 200
    get_response.content = b"name: test\n"

    with patch("lib.sync_cloud._http_request", side_effect=[list_response, get_response]):
        result = provider.pull(since="2026-03-20T00:00:00", config=config)

    assert len(result) == 1
    assert result[0]["path"] == "restarts/test.yaml"


def test_cloud_provider_status(tmp_path):
    """Cloud provider calls /v1/status."""
    from lib.sync_cloud import CloudProvider
    from lib.sync_config import SyncConfig

    config = SyncConfig(
        provider="cloud",
        endpoint="https://recall-api.workers.dev",
        api_key_file=str(tmp_path / "key"),
    )
    (tmp_path / "key").write_text("sk_recall_test123")

    provider = CloudProvider()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "storage": {"used_bytes": 1024, "cap_bytes": 10737418240},
        "limits": {},
        "tier": "lite",
    }

    with patch("lib.sync_cloud._http_request", return_value=mock_response):
        result = provider.status(config)

    assert result["storage"]["used_bytes"] == 1024
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sync_cloud.py -v`
Expected: FAIL

- [ ] **Step 3: Implement cloud provider**

```python
# lib/sync_cloud.py
"""
Cloud sync provider.

Implements SyncProvider for the recall cloud service
(Cloudflare Worker + R2). Uses HTTP REST instead of git.
"""

import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Optional

from lib.sync import SyncProvider, register_provider
from lib.sync_config import SyncConfig


def _read_api_key(config: SyncConfig) -> str:
    """Read API key from the configured file path."""
    key_path = Path(config.api_key_file).expanduser()
    return key_path.read_text().strip()


def _http_request(method: str, url: str, api_key: str, body: bytes = None) -> object:
    """Make an HTTP request to the cloud API."""
    req = urllib.request.Request(url, method=method, data=body)
    req.add_header("Authorization", f"Bearer {api_key}")
    if body:
        req.add_header("Content-Type", "application/octet-stream")

    try:
        response = urllib.request.urlopen(req, timeout=30)
        return _Response(response.status, response.read())
    except urllib.error.HTTPError as e:
        return _Response(e.code, e.read())


class _Response:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content

    def json(self):
        return json.loads(self.content)


class CloudProvider(SyncProvider):
    def push(self, files: List[dict], config: SyncConfig) -> dict:
        api_key = _read_api_key(config)
        endpoint = config.endpoint.rstrip("/")
        pushed = 0
        errors = []

        for f in files:
            url = f"{endpoint}/v1/files/{f['relative_path']}"
            try:
                resp = _http_request("PUT", url, api_key, f["content"])
                if resp.status_code == 200:
                    pushed += 1
                elif resp.status_code == 429:
                    errors.append({"file": f["relative_path"], "error": "rate_limited"})
                    break  # Stop pushing on rate limit
                elif resp.status_code == 507:
                    errors.append({"file": f["relative_path"], "error": "storage_full"})
                    break
                else:
                    errors.append({"file": f["relative_path"], "error": f"HTTP {resp.status_code}"})
            except Exception as e:
                errors.append({"file": f["relative_path"], "error": str(e)})

        return {"pushed": pushed, "errors": errors}

    def pull(self, since: Optional[str], config: SyncConfig) -> List[dict]:
        api_key = _read_api_key(config)
        endpoint = config.endpoint.rstrip("/")

        # List changed files
        list_url = f"{endpoint}/v1/files/"
        if since:
            list_url += f"?after={since}"

        resp = _http_request("GET", list_url, api_key)
        if resp.status_code != 200:
            return []

        file_list = resp.json().get("files", [])
        results = []

        for f in file_list:
            get_url = f"{endpoint}/v1/files/{f['path']}"
            file_resp = _http_request("GET", get_url, api_key)
            if file_resp.status_code == 200:
                results.append({
                    "path": f["path"],
                    "content": file_resp.content,
                })

        return results

    def status(self, config: SyncConfig) -> dict:
        api_key = _read_api_key(config)
        endpoint = config.endpoint.rstrip("/")

        resp = _http_request("GET", f"{endpoint}/v1/status", api_key)
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"HTTP {resp.status_code}"}


register_provider("cloud", CloudProvider)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_sync_cloud.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/sync_cloud.py tests/test_sync_cloud.py
git commit -m "feat: add cloud sync provider adapter for Worker API"
```

---

## Phase 5: Plugin Integration

### Task 14: Hook integration — auto-sync on session end

**Files:**
- Modify: `hooks/scripts/session-end.py`
- Create: `tests/test_sync_hooks.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_sync_hooks.py
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_session_end_triggers_sync_push(tmp_path, monkeypatch):
    """SessionEnd hook calls sync push when auto_sync is enabled."""
    from lib.sync_config import SyncConfig, SyncInclude
    from lib.sync_hooks import maybe_sync_push

    config = SyncConfig(
        provider="cloud",
        endpoint="https://test.workers.dev",
        api_key_file=str(tmp_path / "key"),
        auto_sync=True,
    )
    (tmp_path / "key").write_text("sk_recall_test")

    mock_provider = MagicMock()
    mock_provider.push.return_value = {"pushed": 2, "errors": []}

    with patch("lib.sync_hooks.load_sync_config", return_value=config), \
         patch("lib.sync_hooks.get_provider", return_value=lambda: mock_provider), \
         patch("lib.sync_hooks.gather_sync_files", return_value=[
             {"relative_path": "r/a.yaml", "content": b"x", "secret_findings": []},
             {"relative_path": "r/b.yaml", "content": b"y", "secret_findings": []},
         ]):
        result = maybe_sync_push(data_dir=tmp_path)

    assert result["pushed"] == 2
    mock_provider.push.assert_called_once()


def test_session_end_skips_when_no_config(tmp_path):
    """SessionEnd hook does nothing when sync is not configured."""
    from lib.sync_hooks import maybe_sync_push

    with patch("lib.sync_hooks.load_sync_config", return_value=None):
        result = maybe_sync_push(data_dir=tmp_path)

    assert result is None


def test_session_end_skips_manual_mode(tmp_path):
    """SessionEnd hook skips push in manual mode."""
    from lib.sync_config import SyncConfig
    from lib.sync_hooks import maybe_sync_push

    config = SyncConfig(provider="cloud", mode="manual")

    with patch("lib.sync_hooks.load_sync_config", return_value=config):
        result = maybe_sync_push(data_dir=tmp_path)

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sync_hooks.py -v`
Expected: FAIL

- [ ] **Step 3: Implement sync hook helpers**

```python
# lib/sync_hooks.py
"""
Sync hook integration.

Called from session-start and session-end hooks to auto-push/pull.
Fails silently — never blocks the user's session.
"""

import sys
from pathlib import Path
from typing import Optional

from lib.sync_config import load_sync_config, SyncConfig
from lib.sync import gather_sync_files, get_provider


def maybe_sync_push(data_dir: Path = None) -> Optional[dict]:
    """Push to remote if auto_sync is enabled. Returns result or None."""
    config = load_sync_config()
    if config is None:
        return None
    if config.mode == "manual":
        return None
    if not config.auto_sync:
        return None

    try:
        provider_cls = get_provider(config.provider)
        provider = provider_cls()
        files = gather_sync_files(data_dir or Path.home() / ".claude", config)

        if not files:
            return {"pushed": 0, "errors": []}

        # Filter out files with secret findings in strict mode
        if config.secret_scan == "strict":
            clean_files = [f for f in files if not f["secret_findings"]]
            if len(clean_files) < len(files):
                print(f"  sync: {len(files) - len(clean_files)} files blocked by secret scan", file=sys.stderr)
            files = clean_files

        result = provider.push(files, config)
        if result["pushed"] > 0:
            print(f"  sync: pushed {result['pushed']} files to {config.provider}")
        if result["errors"]:
            print(f"  sync: {len(result['errors'])} errors", file=sys.stderr)
        return result

    except Exception as e:
        print(f"  sync: push failed ({e})", file=sys.stderr)
        return {"pushed": 0, "errors": [str(e)]}


def maybe_sync_pull(data_dir: Path = None) -> Optional[dict]:
    """Pull from remote if auto mode. Returns result or None."""
    config = load_sync_config()
    if config is None:
        return None
    if config.mode == "manual":
        return None

    try:
        provider_cls = get_provider(config.provider)
        provider = provider_cls()

        # Read last pull timestamp
        ts_file = (data_dir or Path.home() / ".claude") / ".last_sync_pull"
        since = ts_file.read_text().strip() if ts_file.exists() else None

        pulled = provider.pull(since=since, config=config)

        # Write files to local directories
        for f in pulled:
            dest = (data_dir or Path.home() / ".claude") / f["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(f["content"], bytes):
                dest.write_bytes(f["content"])
            else:
                dest.write_text(f["content"])

        # Update timestamp
        from datetime import datetime, timezone
        ts_file.parent.mkdir(parents=True, exist_ok=True)
        ts_file.write_text(datetime.now(timezone.utc).isoformat())

        if pulled:
            print(f"  sync: pulled {len(pulled)} files from {config.provider}")
        return {"pulled": len(pulled)}

    except Exception as e:
        print(f"  sync: pull failed ({e})", file=sys.stderr)
        return {"pulled": 0, "error": str(e)}
```

- [ ] **Step 4: Add sync calls to session-end.py**

Add at the end of the `main()` function in `hooks/scripts/session-end.py`, before the final print:

```python
    # Sync push (if configured)
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))
        from sync_hooks import maybe_sync_push
        maybe_sync_push()
    except Exception:
        pass  # Never fail indexing due to sync
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_sync_hooks.py -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add lib/sync_hooks.py tests/test_sync_hooks.py hooks/scripts/session-end.py
git commit -m "feat: add auto-sync push on session end"
```

---

### Task 15: Add sync pull to session-start hook

**Files:**
- Modify: `hooks/scripts/session-start.py`

- [ ] **Step 1: Add sync pull call to session-start.py**

Add near the top of `main()`, before the index is loaded:

```python
    # Sync pull (if configured) — do this before loading index
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'lib'))
        from sync_hooks import maybe_sync_pull
        maybe_sync_pull()
    except Exception:
        pass  # Never block session start due to sync
```

- [ ] **Step 2: Verify session-start still works**

Run: `python3 hooks/scripts/session-start.py /Users/exampleuser/ashcode/recall`
Expected: Shows session context as before, no errors

- [ ] **Step 3: Commit**

```bash
git add hooks/scripts/session-start.py
git commit -m "feat: add auto-sync pull on session start"
```

---

## Phase 6: Microsite Pages

### Task 16: Cloud service page (cloud.html)

**Files:**
- Create: `docs/cloud.html`

- [ ] **Step 1: Create cloud.html**

Build a page using the filing cabinet aesthetic from `docs/index.html`. Include:
- Product pitch: "Git for Agent Sessions — your memory, everywhere"
- Pricing: "$0.50/month, billed $1.50 quarterly, auto-cancels if you stop using it"
- Stripe Checkout button placeholder (will need real Stripe publishable key in env)
- Post-checkout: API key display + setup command
- Link to self-host guide
- Same color palette, fonts, and card/sticky-note components as index.html

The Stripe Checkout integration requires a small JS snippet:

```html
<script src="https://js.stripe.com/v3/"></script>
<script>
  // Replace with actual publishable key at deploy time
  const stripe = Stripe('pk_live_REPLACE_ME');
  document.getElementById('checkout-btn').addEventListener('click', async () => {
    const resp = await fetch('/v1/checkout', { method: 'POST' });
    const { sessionId } = await resp.json();
    stripe.redirectToCheckout({ sessionId });
  });
</script>
```

Note: The Worker needs a `/v1/checkout` endpoint to create the Stripe Checkout session. Add this to `worker/src/stripe.ts`.

- [ ] **Step 2: Commit**

```bash
git add docs/cloud.html
git commit -m "feat: add cloud service microsite page"
```

---

### Task 17: Self-host guide page (self-host.html)

**Files:**
- Create: `docs/self-host.html`

- [ ] **Step 1: Create self-host.html**

Same aesthetic. Step-by-step guide:

1. Fork the repo
2. Create Cloudflare account
3. Create R2 bucket (enable versioning) + KV namespace
4. Create Stripe account + product
5. Set secrets via `wrangler secret put`
6. `wrangler deploy`
7. Configure Stripe webhook URL
8. Update `wrangler.toml` with your KV namespace ID
9. Done — selling under your own brand

Include terminal-style code blocks for each step with copy buttons.

- [ ] **Step 2: Commit**

```bash
git add docs/self-host.html
git commit -m "feat: add self-host deployment guide page"
```

---

## Phase 7: agent-adm Plugin (Separate Directory)

### Task 18: agent-adm plugin scaffold

**Files:**
- Create: `../agent-adm/.claude-plugin/plugin.json`
- Create: `../agent-adm/lib/adm.py`
- Create: `../agent-adm/lib/adm_index.py`
- Create: `../agent-adm/commands/adm.md`
- Create: `../agent-adm/hooks/hooks.json`
- Create: `../agent-adm/hooks/scripts/adm-session-start.py`
- Create: `../agent-adm/tests/test_adm.py`

Note: agent-adm is a separate repo/directory. Create at `../agent-adm/` as a sibling to recall.

- [ ] **Step 1: Create plugin.json**

```json
{
  "name": "agent-adm",
  "version": "1.0.0",
  "description": "Architecture Decision Memos — track, revisit, and evolve architectural choices.",
  "author": { "name": "ashrocket collective" },
  "repository": "https://github.com/ashrocket/agent-adm",
  "license": "MIT",
  "keywords": ["architecture", "decisions", "memos", "tracking", "agent"]
}
```

- [ ] **Step 2: Write failing test for ADM CRUD**

```python
# ../agent-adm/tests/test_adm.py
import pytest
from pathlib import Path

def test_create_adm(tmp_path):
    """Create an ADM and verify it's stored as YAML."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from lib.adm import create_adm, load_adm

    adm = create_adm(
        decision="Use PostgreSQL over DynamoDB",
        arguments_for=["ACID compliance", "Team expertise"],
        arguments_against=["DynamoDB auto-scaling"],
        revisit_date="2026-04-10",
        criteria="P99 query latency <50ms at 1M records",
        project="myapp",
        created_by="claude",
        data_dir=tmp_path,
    )
    assert adm["id"].startswith("adm-")
    assert adm["status"] == "active"

    # Verify file exists
    loaded = load_adm(adm["id"], project="myapp", data_dir=tmp_path)
    assert loaded["decision"] == "Use PostgreSQL over DynamoDB"


def test_list_adms(tmp_path):
    """List ADMs for a project."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from lib.adm import create_adm, list_adms

    create_adm("Decision A", ["pro"], ["con"], "2026-04-10", "", "myapp", "user", tmp_path)
    create_adm("Decision B", ["pro"], ["con"], "2026-04-15", "", "myapp", "claude", tmp_path)

    adms = list_adms(project="myapp", data_dir=tmp_path)
    assert len(adms) == 2


def test_snooze_adm(tmp_path):
    """Snooze an ADM for N days."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from lib.adm import create_adm, snooze_adm, load_adm

    adm = create_adm("Test", ["pro"], ["con"], "2026-03-28", "", "myapp", "user", tmp_path)
    snooze_adm(adm["id"], days=7, project="myapp", data_dir=tmp_path)

    loaded = load_adm(adm["id"], project="myapp", data_dir=tmp_path)
    assert loaded["revisit"]["snoozed_until"] is not None


def test_retire_adm(tmp_path):
    """Retire an ADM."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from lib.adm import create_adm, retire_adm, load_adm

    adm = create_adm("Test", ["pro"], ["con"], "2026-04-10", "", "myapp", "user", tmp_path)
    retire_adm(adm["id"], project="myapp", data_dir=tmp_path)

    loaded = load_adm(adm["id"], project="myapp", data_dir=tmp_path)
    assert loaded["status"] == "retired"


def test_overdue_adms(tmp_path):
    """Find ADMs past their revisit date."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from lib.adm import create_adm, get_overdue_adms

    create_adm("Old", ["pro"], ["con"], "2026-01-01", "", "myapp", "user", tmp_path)
    create_adm("Future", ["pro"], ["con"], "2099-01-01", "", "myapp", "user", tmp_path)

    overdue = get_overdue_adms(project="myapp", data_dir=tmp_path)
    assert len(overdue) == 1
    assert overdue[0]["decision"] == "Old"
```

- [ ] **Step 3: Implement ADM CRUD**

```python
# ../agent-adm/lib/adm.py
"""
Architecture Decision Memo CRUD operations.

ADMs are stored as individual YAML files under
~/.claude/adm/projects/{project}/
"""

import yaml
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional


DEFAULT_DATA_DIR = Path.home() / ".claude" / "adm"


def _adm_dir(project: str, data_dir: Path = None) -> Path:
    base = data_dir or DEFAULT_DATA_DIR
    d = base / "projects" / project
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_adm(
    decision: str,
    arguments_for: List[str],
    arguments_against: List[str],
    revisit_date: str,
    criteria: str,
    project: str,
    created_by: str = "user",
    data_dir: Path = None,
) -> dict:
    adm_id = f"adm-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    adm = {
        "id": adm_id,
        "decision": decision,
        "status": "active",
        "created": now[:10],
        "created_by": created_by,
        "project": project,
        "arguments_for": arguments_for,
        "arguments_against": arguments_against,
        "revisit": {
            "date": revisit_date,
            "criteria": criteria,
            "snoozed_until": None,
        },
        "supersedes": None,
        "superseded_by": None,
        "history": [{"date": now[:10], "action": "created", "note": "Initial decision"}],
    }

    d = _adm_dir(project, data_dir)
    filename = f"{now[:10]}_{decision.lower().replace(' ', '-')[:50]}.yaml"
    filepath = d / filename
    filepath.write_text(yaml.dump(adm, default_flow_style=False, sort_keys=False))

    return adm


def load_adm(adm_id: str, project: str, data_dir: Path = None) -> Optional[dict]:
    d = _adm_dir(project, data_dir)
    for f in d.glob("*.yaml"):
        content = yaml.safe_load(f.read_text())
        if content and content.get("id") == adm_id:
            content["_filepath"] = str(f)
            return content
    return None


def _save_adm(adm: dict, data_dir: Path = None):
    filepath = Path(adm.pop("_filepath"))
    filepath.write_text(yaml.dump(adm, default_flow_style=False, sort_keys=False))


def list_adms(project: str, data_dir: Path = None) -> List[dict]:
    d = _adm_dir(project, data_dir)
    adms = []
    for f in sorted(d.glob("*.yaml")):
        content = yaml.safe_load(f.read_text())
        if content:
            content["_filepath"] = str(f)
            adms.append(content)
    return adms


def snooze_adm(adm_id: str, days: int, project: str, data_dir: Path = None):
    adm = load_adm(adm_id, project, data_dir)
    if not adm:
        return
    until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()[:10]
    adm["revisit"]["snoozed_until"] = until
    adm["history"].append({"date": datetime.now(timezone.utc).isoformat()[:10], "action": "snoozed", "note": f"Snoozed for {days} days"})
    _save_adm(adm, data_dir)


def retire_adm(adm_id: str, project: str, data_dir: Path = None):
    adm = load_adm(adm_id, project, data_dir)
    if not adm:
        return
    adm["status"] = "retired"
    adm["history"].append({"date": datetime.now(timezone.utc).isoformat()[:10], "action": "retired"})
    _save_adm(adm, data_dir)


def get_overdue_adms(project: str, data_dir: Path = None) -> List[dict]:
    today = datetime.now(timezone.utc).isoformat()[:10]
    overdue = []
    for adm in list_adms(project, data_dir):
        if adm["status"] != "active":
            continue
        revisit = adm.get("revisit", {})
        if revisit.get("snoozed_until") and revisit["snoozed_until"] > today:
            continue
        if revisit.get("date") and revisit["date"] <= today:
            overdue.append(adm)
    return overdue
```

- [ ] **Step 4: Run tests**

Run: `cd ../agent-adm && python3 -m pytest tests/test_adm.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Create session-start hook for overdue notifications**

```python
# ../agent-adm/hooks/scripts/adm-session-start.py
#!/usr/bin/env python3
"""SessionStart hook: notify about overdue ADMs."""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def main():
    cwd = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    project = cwd.replace("/", "-")

    try:
        from lib.adm import get_overdue_adms
        overdue = get_overdue_adms(project=project)
        if overdue:
            print(f"adm: {len(overdue)} decision{'s' if len(overdue) > 1 else ''} due for review — /adm review")
    except Exception:
        pass

if __name__ == "__main__":
    main()
```

```json
// ../agent-adm/hooks/hooks.json
[
  {
    "event": "SessionStart",
    "hooks": [
      {
        "type": "command",
        "command": "python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/adm-session-start.py",
        "timeout": 5
      }
    ]
  }
]
```

- [ ] **Step 6: Commit**

```bash
cd ../agent-adm
git init
git add .
git commit -m "feat: initial agent-adm plugin with ADM CRUD and session-start hook"
```

---

## Final: Integration verification

### Task 19: End-to-end smoke test

- [ ] **Step 1: Verify Python sync engine tests all pass**

Run: `cd /Users/exampleuser/ashcode/recall && python3 -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Verify Worker compiles**

Run: `cd worker && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Verify Worker tests pass**

Run: `cd worker && npx vitest run`
Expected: All tests PASS

- [ ] **Step 4: Verify agent-adm tests pass**

Run: `cd ../agent-adm && python3 -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Final commit with updated README**

Add a "Cloud Sync" section to the recall README mentioning `/recall sync init --cloud` and link to the cloud spec.

```bash
git add -A
git commit -m "feat: recall cloud v1 complete"
```
