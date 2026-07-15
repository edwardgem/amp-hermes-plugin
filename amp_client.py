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

    def request_llm_hitl(
        self,
        instance_id: str,
        *,
        execution_id: str = "",
        model: str = "",
        provider: str = "",
        session_id: str = "",
        current_cost_usd: float = 0.0,
        current_cost_status: str = "unknown",
        approved_budget_usd: Optional[float] = None,
        estimated_next_call_cost_usd: float = 0.0,
        estimated_next_call_cost_status: str = "unknown",
        projected_total_cost_usd: float = 0.0,
        projected_total_cost_status: str = "unknown",
        input_tokens_total: int = 0,
        output_tokens_total: int = 0,
        cache_read_tokens_total: int = 0,
        cache_write_tokens_total: int = 0,
        reasoning_tokens_total: int = 0,
        total_tokens: int = 0,
        llm_calls_total: int = 0,
    ) -> Dict[str, Any]:
        """Submit a pre-LLM-call governance signal to AMP and return the policy decision.

        All cost and token fields are promoted to policy params by AMP's flat-field
        promotion mechanism (no AMP schema change required).
        """
        payload: Dict[str, Any] = {
            "caller_id": instance_id,
            "instance_id": instance_id,
            "org_id": self._config.org_id,
            "agent_name": self._config.agent_name,
            "tool": "llm",
            "action": "invoke",
            "context": {
                "model": model,
                "provider": provider,
                "session_id": session_id,
                "execution_id": execution_id,
            },
            "hitl": {"enable": True, "when": "policy"},
            # Flat governance signals — AMP promotes these to policy params automatically
            "execution_id": execution_id,
            "model": model,
            "provider": provider,
            "current_cost_usd": round(current_cost_usd, 8),
            "current_cost_status": current_cost_status,
            "estimated_next_call_cost_usd": round(estimated_next_call_cost_usd, 8),
            "estimated_next_call_cost_status": estimated_next_call_cost_status,
            "projected_total_cost_usd": round(projected_total_cost_usd, 8),
            "projected_total_cost_status": projected_total_cost_status,
            "input_tokens_total": input_tokens_total,
            "output_tokens_total": output_tokens_total,
            "cache_read_tokens_total": cache_read_tokens_total,
            "cache_write_tokens_total": cache_write_tokens_total,
            "reasoning_tokens_total": reasoning_tokens_total,
            "total_tokens": total_tokens,
            "llm_calls_total": llm_calls_total,
        }
        if approved_budget_usd is not None:
            payload["approved_budget_usd"] = round(approved_budget_usd, 8)
        return self._request("POST", "/api/hitl/request", payload)

    def request_plan_approval(
        self,
        instance_id: str,
        *,
        plan_id: str = "",
        plan_type: str = "",
        summary: str = "",
        projected_cost_usd: float = 0.0,
        projected_cost_status: str = "unknown",
        estimated_llm_calls: int = 0,
        estimated_tool_calls: int = 0,
        estimated_duration_minutes: int = 0,
        work_units_total: int = 0,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Submit a proposed execution plan to AMP for governance approval.

        Reuses the same /api/hitl/request path as tool and LLM governance.
        All plan fields are promoted to flat top-level payload fields so AMP's
        eval-policy engine can reference them (e.g. plan_projected_cost_usd)
        without any AMP schema change. `payload` carries caller-specific data
        (e.g. research topics) and is passed through unmodified — AHP does not
        interpret it.
        """
        return self._request(
            "POST",
            "/api/hitl/request",
            {
                "caller_id": instance_id,
                "instance_id": instance_id,
                "org_id": self._config.org_id,
                "agent_name": self._config.agent_name,
                "tool": "execution_plan",
                "action": "submit",
                "context": {
                    "plan_id": plan_id,
                    "summary": summary,
                    "payload": payload or {},
                },
                "hitl": {"enable": True, "when": "policy"},
                # Flat governance signals — AMP promotes these to policy params automatically
                "plan_id": plan_id,
                "plan_type": plan_type,
                "plan_projected_cost_usd": round(float(projected_cost_usd), 8),
                "plan_projected_cost_status": projected_cost_status,
                "plan_estimated_llm_calls": estimated_llm_calls,
                "plan_estimated_tool_calls": estimated_tool_calls,
                "plan_estimated_duration_minutes": estimated_duration_minutes,
                "plan_work_units_total": work_units_total,
            },
        )

    def log_llm_event(
        self,
        instance_id: str,
        event: Dict[str, Any],
        *,
        execution_id: str = "",
    ) -> None:
        """Log a structured LLM call event to AMP."""
        model = event.get("model", "")
        call_num = event.get("api_call_number", "")
        total_tokens = event.get("total_tokens", 0)
        cost_usd = float(event.get("cost_usd") or 0.0)
        cost_status = event.get("cost_status", "unknown")
        parts = []
        if execution_id:
            parts.append(f"execution_id={execution_id}")
        parts.append(
            f"LLM call #{call_num} | model={model} | tokens={total_tokens} | "
            f"cost_usd={cost_usd:.6f} | cost_status={cost_status}"
        )
        self.log(instance_id, " | ".join(parts))

    def log_execution_summary(self, instance_id: str, summary: Dict[str, Any]) -> None:
        """Log a final execution cost/usage summary to AMP."""
        execution_id = summary.get("execution_id", "")
        llm_calls = summary.get("llm_calls", 0)
        total_tokens = summary.get("total_tokens", 0)
        total_cost = float(summary.get("total_cost_usd") or 0.0)
        cost_status = summary.get("cost_status", "unknown")
        self.log(
            instance_id,
            f"Execution summary | execution_id={execution_id} | "
            f"llm_calls={llm_calls} | total_tokens={total_tokens} | "
            f"total_cost_usd={total_cost:.6f} | cost_status={cost_status}",
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
