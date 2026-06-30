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


def test_scan_file_returns_empty_on_ioerror(tmp_path):
    from lib.sync_scan import scan_file
    # Pointing at a nonexistent path triggers IOError
    missing = tmp_path / "nonexistent.yaml"
    results = scan_file(missing)
    assert results == []


def test_scan_detects_private_key():
    from lib.sync_scan import scan_for_secrets
    content = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    findings = scan_for_secrets(content)
    assert len(findings) >= 1
    assert any("key" in f["type"].lower() for f in findings)
