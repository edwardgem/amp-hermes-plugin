from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Any, Dict, Optional

from .amp_client import AmpClient, AmpClientError
from .config import AmpConfig, load_config
from .policy import NormalizedAction, normalize_tool_call
from .session_store import SessionRecord, SessionStore

logger = logging.getLogger(__name__)


def _truncate(value: str, limit: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit - 3]}..."


_FRESHNESS_PATTERNS = [
    re.compile(r"\b(today|latest|current|currently|recent|now|right now)\b", re.IGNORECASE),
    re.compile(r"\b(this week|this month|this year)\b", re.IGNORECASE),
    re.compile(r"\b(live|up-to-date|up to date|as of)\b", re.IGNORECASE),
]

_LIVE_DATA_DOMAIN_PATTERNS = [
    re.compile(r"\b(stock|market|markets|share price|price|prices|earnings|index|indices)\b", re.IGNORECASE),
    re.compile(r"\b(news|headline|headlines|weather|forecast|sports|score|scores)\b", re.IGNORECASE),
]

_EXPLICIT_SEARCH_PATTERNS = [
    re.compile(r"\b(web search|search the web|look up|lookup|find online|search online)\b", re.IGNORECASE),
]


def _needs_live_web_search(user_message: str) -> bool:
    text = str(user_message or "").strip()
    if not text:
        return False
    has_freshness = any(pattern.search(text) for pattern in _FRESHNESS_PATTERNS)
    has_live_domain = any(pattern.search(text) for pattern in _LIVE_DATA_DOMAIN_PATTERNS)
    has_explicit_search = any(pattern.search(text) for pattern in _EXPLICIT_SEARCH_PATTERNS)
    return has_explicit_search or (has_freshness and has_live_domain)


def _build_live_search_context(user_message: str) -> str:
    now = datetime.now(timezone.utc)
    today_utc = f"{now.strftime('%B')} {now.day}, {now.year}"
    return (
        f"Current UTC date: {today_utc}.\n"
        "The user's request appears time-sensitive or explicitly asks for live information.\n"
        "Do not answer from memory for this request.\n"
        "Use the web_search tool first to verify current facts before answering.\n"
        "If live search is unavailable, state that you cannot verify current information."
    )


class AmpGovernancePlugin:
    def __init__(self) -> None:
        self._config: AmpConfig = load_config()
        self._client = AmpClient(self._config)
        self._store = SessionStore()
        self._warned_unconfigured = False
        self._blocked_turn_messages: Dict[str, str] = {}
        self._dispatch_tool = None

    def _warn_unconfigured(self) -> None:
        if self._warned_unconfigured:
            return
        self._warned_unconfigured = True
        logger.warning(
            "amp-governance is not fully configured. Required env vars: "
            "AMP_BACKEND_URL, AMP_API_KEY, AMP_ORG_ID, AMP_USERNAME, AMP_AGENT_NAME or AGENT_NAME"
        )

    def _ensure_instance(
        self,
        session_id: str,
        *,
        model: str = "",
        platform: str = "",
    ) -> str:
        record = self._store.get(session_id)
        if record:
            return record.instance_id
        instance_id = self._client.init_instance(session_id, model, platform)
        self._store.put(
            SessionRecord(
                session_id=session_id,
                instance_id=instance_id,
                model=model,
                platform=platform,
            )
        )
        self._safe_log(instance_id, f"AMP-governed Hermes session started | platform={platform} | model={model}")
        return instance_id

    def _safe_log(self, instance_id: str, message: str, *, level: str = "INFO") -> None:
        try:
            self._client.log(instance_id, message, level=level)
        except Exception as exc:
            logger.warning("amp-governance log failed: %s", exc)

    def _block_message(self, reason: str) -> Dict[str, str]:
        return {"action": "block", "message": reason}

    def _record_blocked_turn(self, session_id: str, reason: str) -> None:
        if not session_id:
            return
        self._blocked_turn_messages[session_id] = reason

    def _consume_blocked_turn_message(self, session_id: str) -> str:
        if not session_id:
            return ""
        return self._blocked_turn_messages.pop(session_id, "")

    def attach_context(self, ctx: Any) -> None:
        self._dispatch_tool = getattr(ctx, "dispatch_tool", None)

    def _build_slack_target(self) -> str:
        try:
            from gateway.session_context import get_session_env
        except Exception:
            return ""
        platform = str(get_session_env("HERMES_SESSION_PLATFORM", "") or "").strip().lower()
        if platform != "slack":
            return ""
        chat_id = str(get_session_env("HERMES_SESSION_CHAT_ID", "") or "").strip()
        if not chat_id:
            return ""
        thread_id = str(get_session_env("HERMES_SESSION_THREAD_ID", "") or "").strip()
        return f"slack:{chat_id}:{thread_id}" if thread_id else f"slack:{chat_id}"

    def _notify_slack(self, message: str) -> None:
        if not callable(self._dispatch_tool):
            return
        target = self._build_slack_target()
        if not target:
            return
        try:
            raw = self._dispatch_tool("send_message", {"target": target, "message": f"[AMP]\n{message}"})
            if not raw:
                return
            payload = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(payload, dict) and payload.get("error"):
                logger.warning("amp-governance slack notify failed: %s", payload["error"])
        except Exception as exc:
            logger.warning("amp-governance slack notify failed: %s", exc)

    def _evaluate_governance(
        self,
        instance_id: str,
        action: NormalizedAction,
    ) -> Optional[Dict[str, str]]:
        self._safe_log(
            instance_id,
            f"Policy check | raw_tool={action.raw_tool_name} | tool={action.tool} | action={action.action} | context={action.context}",
        )
        try:
            response = self._client.request_hitl(instance_id, action)
        except Exception as exc:
            message = f"AMP governance is unavailable; blocked {action.raw_tool_name}. Error: {exc}"
            self._safe_log(instance_id, message, level="ERROR")
            if self._config.fail_closed:
                return self._block_message(message)
            return None

        status = str(response.get("status") or "").strip().lower()
        reason = str(response.get("reason") or response.get("information") or "").strip()
        self._safe_log(
            instance_id,
            f"Policy decision | raw_tool={action.raw_tool_name} | status={status or 'unknown'}{f' | {reason}' if reason else ''}",
        )

        if status == "no_policy":
            return self._block_message(
                f'No active AMP governance policy for agent "{self._config.agent_name}".'
            )

        if status in {"no-hitl", "allow", "allowed", "approved"}:
            return None

        if status in {"pending", "waiting-for-response"} or response.get("workitem_id"):
            deadline = time.time() + (self._config.hitl_timeout_minutes * 60)
            self._safe_log(
                instance_id,
                f"HITL requested | raw_tool={action.raw_tool_name} | waiting_for={self._config.username}",
                level="WARN",
            )
            self._notify_slack(
                f'AMP is waiting for a human reviewer to approve "{action.raw_tool_name}" before continuing. '
                "This action is paused pending review."
            )
            while time.time() < deadline:
                time.sleep(max(self._config.hitl_poll_interval_seconds, 1))
                try:
                    decision = self._client.get_hitl_decision(instance_id)
                except AmpClientError as exc:
                    logger.warning("amp-governance decision poll failed: %s", exc)
                    continue
                if str(decision.get("status") or "").strip().lower() != "complete":
                    continue
                resolution = str(decision.get("resolution") or "").strip().lower()
                info = str(decision.get("information") or "").strip()
                self._safe_log(
                    instance_id,
                    f"HITL resolution | raw_tool={action.raw_tool_name} | resolution={resolution}{f' | {info}' if info else ''}",
                    level="WARN" if resolution not in {"approve", "approved", "modify", "modified"} else "INFO",
                )
                if resolution in {"approve", "approved", "modify", "modified"}:
                    approval_message = (
                        f'AMP review approved "{action.raw_tool_name}" with modifications. Continuing now.'
                        if resolution in {"modify", "modified"}
                        else f'AMP review approved "{action.raw_tool_name}". Continuing now.'
                    )
                    self._notify_slack(approval_message)
                    return None
                self._notify_slack(
                    f'AMP reviewer rejected "{action.raw_tool_name}".{f" {info}" if info else ""}'
                )
                return self._block_message(
                    f'{action.raw_tool_name} was rejected by AMP HITL review.{f" {info}" if info else ""}'
                )
            self._notify_slack(
                f'AMP review timed out for "{action.raw_tool_name}". The action was blocked.'
            )
            return self._block_message(
                f'{action.raw_tool_name} timed out waiting for AMP HITL approval.'
            )

        if self._config.fail_closed:
            return self._block_message(
                f'AMP returned unexpected status "{status or "unknown"}" for {action.raw_tool_name}; blocked.'
            )
        return None

    def on_session_start(self, session_id: str = "", model: str = "", platform: str = "", **_: Any) -> None:
        if not session_id:
            return
        if not self._config.is_configured:
            self._warn_unconfigured()
            return
        try:
            self._ensure_instance(session_id, model=model, platform=platform)
        except Exception as exc:
            logger.warning("amp-governance session init failed: %s", exc)

    def on_session_finalize(self, session_id: str = "", reason: str = "", **_: Any) -> None:
        if not session_id:
            return
        self._blocked_turn_messages.pop(session_id, None)
        record = self._store.get(session_id)
        if not record:
            return
        try:
            self._safe_log(record.instance_id, f"Finalizing session | reason={reason or 'unknown'}")
            self._client.set_state(record.instance_id, "finished")
        except Exception as exc:
            logger.warning("amp-governance finalize failed: %s", exc)
        finally:
            self._store.delete(session_id)

    def pre_llm_call(self, session_id: str = "", user_message: str = "", model: str = "", platform: str = "", **_: Any) -> None:
        if not session_id or not self._config.is_configured:
            if not self._config.is_configured:
                self._warn_unconfigured()
            return None
        try:
            self._blocked_turn_messages.pop(session_id, None)
            instance_id = self._ensure_instance(session_id, model=model, platform=platform)
            if user_message:
                self._safe_log(instance_id, f"User prompt: {_truncate(user_message)}")
            if _needs_live_web_search(user_message):
                context = _build_live_search_context(user_message)
                self._safe_log(instance_id, "Freshness routing | injected live-search context")
                return {"context": context}
        except Exception as exc:
            logger.warning("amp-governance pre_llm_call failed: %s", exc)
        return None

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
        if not self._config.is_configured:
            self._warn_unconfigured()
            if self._config.fail_closed:
                return self._block_message(
                    f'AMP governance is not configured; blocked governed tool "{tool_name}".'
                )
            return None
        try:
            instance_id = self._ensure_instance(session_id, model=model, platform=platform)
            decision = self._evaluate_governance(instance_id, action)
            if decision and decision.get("action") == "block":
                self._record_blocked_turn(session_id, str(decision.get("message") or ""))
            return decision
        except Exception as exc:
            logger.warning("amp-governance pre_tool_call failed: %s", exc)
            if self._config.fail_closed:
                message = (
                    f'AMP governance failed while checking "{tool_name}": {exc}'
                )
                self._record_blocked_turn(session_id, message)
                return self._block_message(message)
            return None

    def post_tool_call(
        self,
        tool_name: str = "",
        args: Any = None,
        session_id: str = "",
        status: str = "",
        duration_ms: Any = None,
        error_message: str = "",
        result: Any = None,
        **_: Any,
    ) -> None:
        action = normalize_tool_call(tool_name, args)
        if action is None:
            return
        if not self._config.is_configured:
            return
        record = self._store.get(session_id)
        if not record:
            return
        summary = f"Tool result | raw_tool={tool_name} | normalized={action.tool}/{action.action} | status={status or 'unknown'}"
        if duration_ms is not None:
            summary += f" | duration_ms={duration_ms}"
        if error_message:
            summary += f" | error={_truncate(error_message, 180)}"
        elif result:
            summary += f" | result={_truncate(str(result), 180)}"
        self._safe_log(
            record.instance_id,
            summary,
            level="ERROR" if (status or "").lower() in {"error", "blocked"} else "INFO",
        )

    def transform_llm_output(
        self,
        response_text: str = "",
        session_id: str = "",
        **_: Any,
    ) -> Optional[str]:
        blocked_reason = self._consume_blocked_turn_message(session_id)
        if not blocked_reason:
            return None
        return "This request is blocked by AMP governance. No action was taken."


_PLUGIN = AmpGovernancePlugin()


def register(ctx) -> None:
    _PLUGIN.attach_context(ctx)
    ctx.register_hook("on_session_start", _PLUGIN.on_session_start)
    ctx.register_hook("on_session_finalize", _PLUGIN.on_session_finalize)
    ctx.register_hook("pre_llm_call", _PLUGIN.pre_llm_call)
    ctx.register_hook("pre_tool_call", _PLUGIN.pre_tool_call)
    ctx.register_hook("post_tool_call", _PLUGIN.post_tool_call)
    ctx.register_hook("transform_llm_output", _PLUGIN.transform_llm_output)
