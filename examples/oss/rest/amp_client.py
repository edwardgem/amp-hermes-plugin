from __future__ import annotations

import json
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import AmpOssConfig


class AmpOssClientError(RuntimeError):
    pass


class AmpOssClient:
    """Raw urllib client for amp-community's OSS REST API (`/api/v0/...`).

    Zero third-party dependencies — same convention as amp-governance's
    own SaaS client (../../amp_client.py), just pointed at a different API
    surface: amp-community's `Bearer` token auth and org-free request
    shape, not amp-backend's `X-API-Key`/`org_id` model. See the
    sdk-python/ example for the same governance logic built on
    amp-sdk-python instead of hand-rolled HTTP calls.
    """

    def __init__(self, config: AmpOssConfig) -> None:
        self._config = config

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.agent_token}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self._config.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8") or "{}"
                return json.loads(body)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise AmpOssClientError(f"HTTP {exc.code}: {body or exc.reason}") from exc
        except URLError as exc:
            raise AmpOssClientError(str(exc.reason)) from exc

    def submit_request(
        self, policy_id: str, tool: str, action: str, params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """POST /api/v0/requests -> {request_id, status, reason, hitl_id, ...}.
        status is one of "allowed" | "denied" | "pending_review"."""
        return self._request(
            "POST", "/api/v0/requests",
            {"policy_id": policy_id, "tool": tool, "action": action, "params": params},
        )

    def get_request(self, request_id: str) -> Dict[str, Any]:
        """GET /api/v0/requests/{id} -- poll while status == "pending".
        Terminal statuses: approved | rejected | modified | resumed |
        expired | cancelled."""
        return self._request("GET", f"/api/v0/requests/{request_id}")
