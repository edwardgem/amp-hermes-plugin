from __future__ import annotations

import json
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Platforms that have no gateway channel to notify back to.
_NON_GATEWAY_PLATFORMS = frozenset({"cli", "cron", "test", ""})


def build_notification_target() -> str:
    """
    Return a Hermes send_message target for the current session's originating channel.

    Returns an empty string when:
    - running in CLI or cron mode (no channel to send back to)
    - gateway session context is not available
    - chat_id is absent from session context

    Target format follows Hermes send_message conventions:
      "platform:chat_id"             (no thread)
      "platform:chat_id:thread_id"   (with thread)

    Supported platforms: slack, telegram, discord, signal, matrix, ntfy, and any
    other platform whose name is set in HERMES_SESSION_PLATFORM.
    """
    try:
        from gateway.session_context import get_session_env
    except Exception:
        return ""
    platform = str(get_session_env("HERMES_SESSION_PLATFORM", "") or "").strip().lower()
    if platform in _NON_GATEWAY_PLATFORMS:
        return ""
    chat_id = str(get_session_env("HERMES_SESSION_CHAT_ID", "") or "").strip()
    if not chat_id:
        return ""
    thread_id = str(get_session_env("HERMES_SESSION_THREAD_ID", "") or "").strip()
    return f"{platform}:{chat_id}:{thread_id}" if thread_id else f"{platform}:{chat_id}"


def notify_user(
    dispatch_tool: Optional[Callable],
    message: str,
    *,
    notifications_enabled: bool = True,
) -> None:
    """
    Send a best-effort governance notification to the originating channel.

    Delivery failures are caught, logged as warnings, and swallowed.
    Governance enforcement is never conditional on delivery success.

    Does nothing when:
    - notifications_enabled is False
    - dispatch_tool is not callable (no gateway context)
    - the current session has no notification target (CLI, missing context)
    """
    if not notifications_enabled:
        return
    if not callable(dispatch_tool):
        return
    target = build_notification_target()
    if not target:
        return
    try:
        raw = dispatch_tool("send_message", {"target": target, "message": f"[AMP]\n{message}"})
        if not raw:
            return
        payload = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(payload, dict) and payload.get("error"):
            logger.warning("amp-governance notify failed: %s", payload["error"])
    except Exception as exc:
        logger.warning("amp-governance notify failed: %s", exc)
