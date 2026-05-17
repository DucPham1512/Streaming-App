"""Tiny HTTP client for talking to the Flask backend.

Lives in its own module so both __main__.py and the recording state
machine in loop.py / recording.py can share it without circular
imports. Standard-library only (urllib) to keep the broadcaster's
runtime deps small.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


class ApiError(RuntimeError):
    """Wraps a non-2xx response or transport failure from the backend."""


class ApiClient:
    """Synchronous JSON-over-HTTP client scoped to a single api_base + key.

    Usage:
        api = ApiClient("http://localhost:5001", api_key=None)
        resp = api.post("/api/v1/streams", {"title": "demo"})
        templates = api.get("/api/v1/gestures/templates")["templates"]

    All methods raise `ApiError` on failure; callers decide whether to
    surface or swallow.
    """

    def __init__(self, api_base: str, api_key: str | None):
        self._base = api_base.rstrip("/")
        self._api_key = api_key

    # ------------------------------------------------------------------
    # Verb helpers
    # ------------------------------------------------------------------

    def get(self, path: str) -> dict:
        return self._call("GET", path, None)

    def post(self, path: str, body: dict | None = None) -> dict:
        return self._call("POST", path, body)

    def patch(self, path: str, body: dict | None = None) -> dict:
        return self._call("PATCH", path, body)

    def delete(self, path: str) -> dict:
        return self._call("DELETE", path, None)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call(self, method: str, path: str, body: dict | None) -> dict:
        url = f"{self._base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self._api_key:
            req.add_header("Authorization", f"Bearer {self._api_key}")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body_text = e.read().decode()[:200]
            raise ApiError(f"{method} {url} → HTTP {e.code}: {body_text}") from e
        except Exception as e:
            raise ApiError(f"{method} {url} failed: {e}") from e
