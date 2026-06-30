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
