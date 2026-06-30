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


def _read_api_key(config: SyncConfig) -> str:
    key_path = Path(config.api_key_file).expanduser()
    return key_path.read_text().strip()


def _http_request(method: str, url: str, api_key: str, body: bytes = None) -> object:
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
                    break
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
