"""Optimistic-concurrency sync: base-sha state and the precondition wiring."""

import pytest
from unittest.mock import patch, MagicMock

from lib.sync_config import SyncConfig
from lib.sync_state import SyncState, content_sha256, is_sha256


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    monkeypatch.setenv("RECALL_STATE_DIR", str(tmp_path / "state"))


def _config(tmp_path):
    (tmp_path / "key").write_text("sk_test")
    return SyncConfig(
        provider="cloud",
        endpoint="https://recall-api.workers.dev",
        api_key_file=str(tmp_path / "key"),
    )


def test_is_sha256_only_accepts_real_digests():
    assert is_sha256("a" * 64)
    assert not is_sha256("A" * 64)          # uppercase is not our hex form
    assert not is_sha256("abc")             # too short
    assert not is_sha256(MagicMock())       # never trust a mocked value into state
    assert not is_sha256(None)


def test_state_roundtrip_and_isolation():
    s = SyncState("https://example.test")
    assert s.base("learnings/x.yaml") is None
    s.record("learnings/x.yaml", content_sha256(b"hello"))
    s.save()

    reloaded = SyncState("https://example.test")
    assert reloaded.base("learnings/x.yaml") == content_sha256(b"hello")

    # A different endpoint never shares a manifest.
    other = SyncState("https://other.test")
    assert other.base("learnings/x.yaml") is None

    reloaded.forget("learnings/x.yaml")
    reloaded.save()
    assert SyncState("https://example.test").base("learnings/x.yaml") is None


def test_push_sends_create_only_when_no_base(tmp_path):
    from lib.sync_cloud import CloudProvider

    ok = MagicMock()
    ok.status_code = 200
    ok.content = b'{"content_sha256":"%s"}' % (b"a" * 64)
    ok.json.return_value = {"content_sha256": "a" * 64}

    with patch("lib.sync_cloud._http_request", return_value=ok) as req:
        result = CloudProvider().push(
            [{"relative_path": "learnings/x.yaml", "content": b"body"}], _config(tmp_path)
        )

    assert result["pushed"] == 1
    headers = req.call_args.kwargs["headers"]
    assert headers == {"If-None-Match": "*"}


def test_push_sends_if_match_when_base_known(tmp_path):
    from lib.sync_cloud import CloudProvider

    base = content_sha256(b"old")
    state = SyncState("https://recall-api.workers.dev")
    state.record("learnings/x.yaml", base)
    state.save()

    ok = MagicMock()
    ok.status_code = 200
    ok.content = b"{}"
    ok.json.return_value = {}

    with patch("lib.sync_cloud._http_request", return_value=ok) as req:
        CloudProvider().push(
            [{"relative_path": "learnings/x.yaml", "content": b"new"}], _config(tmp_path)
        )

    assert req.call_args.kwargs["headers"] == {"If-Match": base}


def test_push_surfaces_conflict_without_clobber(tmp_path):
    from lib.sync_cloud import CloudProvider

    conflict = MagicMock()
    conflict.status_code = 412
    conflict.json.return_value = {"current_content_sha256": "b" * 64}

    with patch("lib.sync_cloud._http_request", return_value=conflict):
        result = CloudProvider().push(
            [{"relative_path": "learnings/x.yaml", "content": b"mine"}], _config(tmp_path)
        )

    assert result["pushed"] == 0
    assert result["conflicts"] == [
        {"file": "learnings/x.yaml", "current_content_sha256": "b" * 64}
    ]
    # A conflict must not record a base — we never saw the server's version.
    assert SyncState("https://recall-api.workers.dev").base("learnings/x.yaml") is None


def test_push_surfaces_secret_rejection(tmp_path):
    from lib.sync_cloud import CloudProvider

    rejected = MagicMock()
    rejected.status_code = 422
    rejected.json.return_value = {"error": "content_secret"}

    with patch("lib.sync_cloud._http_request", return_value=rejected):
        result = CloudProvider().push(
            [{"relative_path": "learnings/leak.yaml", "content": b"AKIA................"}],
            _config(tmp_path),
        )

    assert result["pushed"] == 0
    assert result["errors"] == [{"file": "learnings/leak.yaml", "error": "content_secret"}]


def test_pull_records_base_from_header(tmp_path):
    from lib.sync_cloud import CloudProvider

    listing = MagicMock()
    listing.status_code = 200
    listing.json.return_value = {"files": [{"path": "learnings/x.yaml"}]}

    served = MagicMock()
    served.status_code = 200
    served.content = b"body"
    served.headers = {"X-Content-Sha256": content_sha256(b"body")}

    with patch("lib.sync_cloud._http_request", side_effect=[listing, served]):
        result = CloudProvider().pull(None, _config(tmp_path))

    assert len(result) == 1
    # The pulled sha becomes the base for the next push.
    assert SyncState("https://recall-api.workers.dev").base("learnings/x.yaml") == content_sha256(b"body")
