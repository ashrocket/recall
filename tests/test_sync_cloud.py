import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_cloud_provider_push(tmp_path):
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


def test_cloud_provider_push_rate_limited(tmp_path):
    from lib.sync_cloud import CloudProvider
    from lib.sync_config import SyncConfig

    config = SyncConfig(provider="cloud", endpoint="https://recall-api.workers.dev", api_key_file=str(tmp_path / "key"))
    (tmp_path / "key").write_text("sk_test")

    provider = CloudProvider()
    files = [
        {"relative_path": "a.json", "content": b"x", "secret_findings": []},
        {"relative_path": "b.json", "content": b"y", "secret_findings": []},
    ]

    rate_limited = MagicMock()
    rate_limited.status_code = 429

    with patch("lib.sync_cloud._http_request", return_value=rate_limited):
        result = provider.push(files, config)

    assert result["pushed"] == 0
    assert any("rate_limited" in str(e) for e in result["errors"])


def test_cloud_provider_status_error_response(tmp_path):
    from lib.sync_cloud import CloudProvider
    from lib.sync_config import SyncConfig

    config = SyncConfig(provider="cloud", endpoint="https://recall-api.workers.dev", api_key_file=str(tmp_path / "key"))
    (tmp_path / "key").write_text("sk_test")

    provider = CloudProvider()

    err_response = MagicMock()
    err_response.status_code = 401

    with patch("lib.sync_cloud._http_request", return_value=err_response):
        result = provider.status(config)

    assert "error" in result
    assert "401" in result["error"]


def test_cloud_provider_push_storage_full(tmp_path):
    """507 storage-full error breaks the loop immediately."""
    from lib.sync_cloud import CloudProvider
    from lib.sync_config import SyncConfig

    config = SyncConfig(provider="cloud", endpoint="https://recall-api.workers.dev", api_key_file=str(tmp_path / "key"))
    (tmp_path / "key").write_text("sk_test")

    provider = CloudProvider()
    files = [
        {"relative_path": "a.yaml", "content": b"x", "secret_findings": []},
        {"relative_path": "b.yaml", "content": b"y", "secret_findings": []},
    ]

    full = MagicMock()
    full.status_code = 507

    with patch("lib.sync_cloud._http_request", return_value=full) as mock_req:
        result = provider.push(files, config)

    assert result["pushed"] == 0
    assert any("storage_full" in str(e) for e in result["errors"])
    assert mock_req.call_count == 1  # break stops after first file


def test_cloud_provider_push_records_exception_error(tmp_path):
    """When _http_request raises an exception, error is captured per-file."""
    from lib.sync_cloud import CloudProvider
    from lib.sync_config import SyncConfig

    config = SyncConfig(provider="cloud", endpoint="https://recall-api.workers.dev", api_key_file=str(tmp_path / "key"))
    (tmp_path / "key").write_text("sk_test")

    provider = CloudProvider()
    files = [{"relative_path": "a.yaml", "content": b"x", "secret_findings": []}]

    with patch("lib.sync_cloud._http_request", side_effect=ConnectionError("network down")):
        result = provider.push(files, config)

    assert result["pushed"] == 0
    assert len(result["errors"]) == 1
    assert "network down" in result["errors"][0]["error"]


def test_cloud_provider_push_records_generic_http_error(tmp_path):
    """Non-200/429/507 status code is recorded as 'HTTP N' error and continues."""
    from lib.sync_cloud import CloudProvider
    from lib.sync_config import SyncConfig

    config = SyncConfig(provider="cloud", endpoint="https://recall-api.workers.dev", api_key_file=str(tmp_path / "key"))
    (tmp_path / "key").write_text("sk_test")

    provider = CloudProvider()
    files = [
        {"relative_path": "a.yaml", "content": b"x", "secret_findings": []},
        {"relative_path": "b.yaml", "content": b"y", "secret_findings": []},
    ]

    bad_resp = MagicMock()
    bad_resp.status_code = 403

    ok_resp = MagicMock()
    ok_resp.status_code = 200

    with patch("lib.sync_cloud._http_request", side_effect=[bad_resp, ok_resp]) as mock_req:
        result = provider.push(files, config)

    assert result["pushed"] == 1
    assert any("HTTP 403" in str(e) for e in result["errors"])
    assert mock_req.call_count == 2  # continues after generic error


def test_cloud_provider_pull_returns_empty_on_list_failure(tmp_path):
    """pull() returns [] when the file-list endpoint returns non-200."""
    from lib.sync_cloud import CloudProvider
    from lib.sync_config import SyncConfig

    config = SyncConfig(provider="cloud", endpoint="https://recall-api.workers.dev", api_key_file=str(tmp_path / "key"))
    (tmp_path / "key").write_text("sk_test")

    provider = CloudProvider()

    bad_list = MagicMock()
    bad_list.status_code = 503

    with patch("lib.sync_cloud._http_request", return_value=bad_list):
        result = provider.pull(since=None, config=config)

    assert result == []


def test_cloud_provider_pull_skips_failed_file_fetch(tmp_path):
    """pull() skips files where the individual GET returns non-200."""
    from lib.sync_cloud import CloudProvider
    from lib.sync_config import SyncConfig

    config = SyncConfig(provider="cloud", endpoint="https://recall-api.workers.dev", api_key_file=str(tmp_path / "key"))
    (tmp_path / "key").write_text("sk_test")

    provider = CloudProvider()

    list_resp = MagicMock()
    list_resp.status_code = 200
    list_resp.json.return_value = {"files": [{"path": "a.yaml"}, {"path": "b.yaml"}]}

    ok_file = MagicMock()
    ok_file.status_code = 200
    ok_file.content = b"content-a"

    missing_file = MagicMock()
    missing_file.status_code = 404

    with patch("lib.sync_cloud._http_request", side_effect=[list_resp, ok_file, missing_file]):
        result = provider.pull(since=None, config=config)

    assert len(result) == 1
    assert result[0]["path"] == "a.yaml"
