"""
Cloud sync provider.
Implements SyncProvider for the recall cloud service.
"""

import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Optional

from lib.sync import SyncProvider, register_provider
from lib.sync_config import SyncConfig
from lib.sync_state import SyncState, content_sha256, is_sha256


def _read_api_key(config: SyncConfig) -> str:
    key_path = Path(config.api_key_file).expanduser()
    return key_path.read_text().strip()


def _http_request(method: str, url: str, api_key: str, body: bytes = None,
                  headers: dict = None) -> object:
    req = urllib.request.Request(url, method=method, data=body)
    req.add_header("Authorization", f"Bearer {api_key}")
    if body:
        req.add_header("Content-Type", "application/octet-stream")
    for name, value in (headers or {}).items():
        req.add_header(name, value)

    try:
        response = urllib.request.urlopen(req, timeout=30)
        return _Response(response.status, response.read(), dict(response.headers))
    except urllib.error.HTTPError as e:
        return _Response(e.code, e.read(), dict(e.headers))


class _Response:
    def __init__(self, status_code: int, content: bytes, headers: dict = None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    def json(self):
        return json.loads(self.content)


class CloudProvider(SyncProvider):
    def push(self, files: List[dict], config: SyncConfig) -> dict:
        api_key = _read_api_key(config)
        endpoint = config.endpoint.rstrip("/")
        state = SyncState(endpoint)
        pushed = 0
        conflicts = []
        errors = []

        for f in files:
            rel = f["relative_path"]
            url = f"{endpoint}/v1/files/{rel}"

            # Optimistic concurrency: only overwrite the version we based this edit on.
            # With no recorded base, ask for create-only so we surface — rather than
            # clobber — a file another machine already pushed.
            base = state.base(rel)
            precond = {"If-Match": base} if base else {"If-None-Match": "*"}

            try:
                resp = _http_request("PUT", url, api_key, f["content"], headers=precond)
                if resp.status_code == 200:
                    pushed += 1
                    new_sha = None
                    try:
                        new_sha = resp.json().get("content_sha256")
                    except Exception:
                        new_sha = None
                    if not is_sha256(new_sha):
                        new_sha = content_sha256(f["content"])
                    state.record(rel, new_sha)
                elif resp.status_code == 412:
                    # Someone else moved it. Do not clobber; report so the caller can pull.
                    current = None
                    try:
                        current = resp.json().get("current_content_sha256")
                    except Exception:
                        pass
                    conflicts.append({"file": rel, "current_content_sha256": current})
                elif resp.status_code == 422:
                    errors.append({"file": rel, "error": "content_secret"})
                elif resp.status_code == 429:
                    errors.append({"file": rel, "error": "rate_limited"})
                    break
                elif resp.status_code == 507:
                    errors.append({"file": rel, "error": "storage_full"})
                    break
                else:
                    errors.append({"file": rel, "error": f"HTTP {resp.status_code}"})
            except Exception as e:
                errors.append({"file": rel, "error": str(e)})

        state.save()
        return {"pushed": pushed, "conflicts": conflicts, "errors": errors}

    def pull(self, since: Optional[str], config: SyncConfig) -> List[dict]:
        api_key = _read_api_key(config)
        endpoint = config.endpoint.rstrip("/")
        state = SyncState(endpoint)

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
                # Record what we just read as the base for this path's next push.
                sha = file_resp.headers.get("X-Content-Sha256")
                if not is_sha256(sha):
                    sha = f.get("content_sha256")
                if not is_sha256(sha) and isinstance(file_resp.content, (bytes, bytearray)):
                    sha = content_sha256(file_resp.content)
                if is_sha256(sha):
                    state.record(f["path"], sha)
                results.append({
                    "path": f["path"],
                    "content": file_resp.content,
                })

        state.save()
        return results

    def status(self, config: SyncConfig) -> dict:
        api_key = _read_api_key(config)
        endpoint = config.endpoint.rstrip("/")

        resp = _http_request("GET", f"{endpoint}/v1/status", api_key)
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"HTTP {resp.status_code}"}


register_provider("cloud", CloudProvider)
