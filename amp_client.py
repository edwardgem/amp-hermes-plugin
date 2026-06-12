from __future__ import annotations

import json
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import AmpConfig
from .policy import NormalizedAction


class AmpClientError(RuntimeError):
    pass


class AmpClient:
    def __init__(self, config: AmpConfig) -> None:
        self._config = config

    def _headers(self) -> Dict[str, str]:
        return {
            "X-API-Key": self._config.api_key,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self._config.backend_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8") or "{}"
                return json.loads(body)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise AmpClientError(f"HTTP {exc.code}: {body or exc.reason}") from exc
        except URLError as exc:
            raise AmpClientError(str(exc.reason)) from exc

    def init_instance(self, session_id: str, model: str, platform: str) -> str:
        data = self._request(
            "POST",
            "/api/agent/init",
            {
                "agent_name": self._config.agent_name,
                "org_id": self._config.org_id,
                "username": self._config.username,
                "prompt": "Hermes governance session",
                "auto_start": True,
                "config": {"agent_mode": "polling"},
                "metadata": {
                    "source": "hermes-amp-plugin",
                    "session_id": session_id,
                    "platform": platform,
                    "model": model,
                },
            },
        )
        instance_id = str(data.get("instance_id") or "").strip()
        if not instance_id:
            raise AmpClientError("AMP did not return instance_id")
        return instance_id

    def log(
        self,
        instance_id: str,
        message: str,
        *,
        level: str = "INFO",
    ) -> None:
        self._request(
            "POST",
            "/api/log",
            {
                "instance_id": instance_id,
                "service": self._config.agent_name,
                "level": level,
                "message": message,
                "org_id": self._config.org_id,
                "username": self._config.username,
            },
        )

    def request_hitl(self, instance_id: str, action: NormalizedAction) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/hitl/request",
            {
                "caller_id": instance_id,
                "instance_id": instance_id,
                "org_id": self._config.org_id,
                "agent_name": self._config.agent_name,
                "tool": action.tool,
                "action": action.action,
                "context": action.context,
                "hitl": {
                    "enable": True,
                    "when": "policy",
                },
            },
        )

    def get_hitl_decision(self, instance_id: str) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/api/hitl/get-decision",
            query={"caller_id": instance_id},
        )

    def set_state(self, instance_id: str, state: str) -> None:
        self._request(
            "POST",
            "/api/agent/setState",
            {
                "agent_name": self._config.agent_name,
                "instance_id": instance_id,
                "state": state,
            },
        )
