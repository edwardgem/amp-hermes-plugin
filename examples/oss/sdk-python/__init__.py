from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from inquiryon_amp_sdk import AmpClient
from inquiryon_amp_sdk.errors import AmpError, TimeoutError_
from inquiryon_amp_sdk.models import SubmitGovernedRequestInput

from .config import load_config
from .policy import normalize_tool_call

logger = logging.getLogger(__name__)


class AmpOssSdkPlugin:
    """Minimal Hermes plugin governing tool calls through amp-community's
    self-hosted OSS API using the amp-sdk-python typed client. Same policy,
    same governance logic as ../rest/ -- only the client differs. See
    README.md for setup, including the extra `pip install` step this
    variant needs that the rest/ example doesn't."""

    def __init__(self) -> None:
        self._config = load_config()
        self._client: Optional[AmpClient] = None
        if self._config.is_configured:
            self._client = AmpClient(self._config.base_url, self._config.agent_token)
        self._warned = False

    def _warn_unconfigured(self) -> None:
        if not self._warned:
            logger.warning(
                "amp-oss-sdk-example is not configured -- set AMP_OSS_BASE_URL "
                "and AMP_OSS_AGENT_TOKEN in ~/.hermes/.env. See this plugin's README.md."
            )
            self._warned = True

    @staticmethod
    def _block(reason: str) -> Dict[str, str]:
        return {"action": "block", "message": reason}

    def pre_tool_call(
        self,
        tool_name: str = "",
        args: Any = None,
        session_id: str = "",
        model: str = "",
        platform: str = "",
        **_: Any,
    ) -> Optional[Dict[str, str]]:
        action = normalize_tool_call(tool_name, args)
        if action is None:
            return None
        if not self._config.is_configured or self._client is None:
            self._warn_unconfigured()
            if self._config.fail_closed:
                return self._block(f'AMP OSS governance is not configured; blocked "{tool_name}".')
            return None
        try:
            result = self._client.submit_governed_request(SubmitGovernedRequestInput(
                policy_id=self._config.policy_id,
                tool=action.tool,
                action=action.action,
                params=action.context,
            ))
        except AmpError as exc:
            message = f'AMP OSS governance is unavailable; blocked "{tool_name}". Error: {exc.message}'
            logger.warning(message)
            return self._block(message) if self._config.fail_closed else None

        status = result.get("status")
        if status == "allowed":
            return None
        if status == "denied":
            reason = str(result.get("reason") or "").strip()
            return self._block(f'"{tool_name}" was denied by AMP policy.{f" {reason}" if reason else ""}')
        if status == "pending_review":
            return self._await_decision(tool_name, str(result.get("request_id") or ""))
        if self._config.fail_closed:
            return self._block(f'AMP returned unexpected status "{status}" for "{tool_name}"; blocked.')
        return None

    def _await_decision(self, tool_name: str, request_id: str) -> Optional[Dict[str, str]]:
        if not request_id or self._client is None:
            return self._block(f'AMP did not return a request_id for "{tool_name}"; blocked.')
        try:
            final = self._client.wait_for_decision(
                request_id,
                interval_s=max(self._config.hitl_poll_interval_seconds, 1),
                timeout_s=self._config.hitl_timeout_minutes * 60,
            )
        except TimeoutError_:
            return self._block(f'"{tool_name}" timed out waiting for AMP HITL approval.')
        except AmpError as exc:
            logger.warning("amp-oss-sdk-example wait_for_decision failed: %s", exc.message)
            return self._block(f'AMP OSS governance failed while waiting on "{tool_name}": {exc.message}')

        # final.status is a generic terminal marker ("resumed"/"closed");
        # the actual outcome is the separate "decision" field.
        decision = str(final.get("decision") or "")
        if decision == "approved":
            return None
        if decision == "modified":
            # The original call was NOT executed -- amp-community spawns a
            # new follow-up review for the modified params instead of
            # resuming this one. Treating this as "allow" would tell
            # Hermes to proceed with params that were never approved.
            follow_up = final.get("follow_up_hitl_id") or ""
            return self._block(
                f'"{tool_name}" was not approved as submitted; AMP recorded a '
                f"modified version pending further review"
                + (f" (hitl {follow_up})" if follow_up else "") + "."
            )
        return self._block(f'"{tool_name}" was {decision or "rejected"} by AMP HITL review.')


_PLUGIN = AmpOssSdkPlugin()


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _PLUGIN.pre_tool_call)
