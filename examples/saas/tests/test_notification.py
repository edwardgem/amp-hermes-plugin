from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

ROOT = Path(__file__).resolve().parent.parent
ROOT_PARENT = ROOT.parent
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from hermes.notification import build_notification_target, notify_user


def _make_dispatch(return_value=None) -> Mock:
    m = Mock()
    if return_value is not None:
        m.return_value = json.dumps(return_value) if isinstance(return_value, dict) else return_value
    else:
        m.return_value = json.dumps({"success": True})
    return m


def _patch_session(**vars) -> "contextlib.AbstractContextManager":
    """Patch get_session_env to return values from vars dict, default empty string."""
    def fake_get_session_env(name, default=""):
        return vars.get(name, default)

    return patch("hermes.notification.build_notification_target.__globals__", {})


class BuildNotificationTargetTests(unittest.TestCase):
    def _build_with_env(self, **session_vars) -> str:
        def fake_env(name, default=""):
            return session_vars.get(name, default)

        with patch("hermes.notification.build_notification_target") as mock_fn:
            # Re-implement inline with patch
            pass

        # Call the real function with patched gateway import
        with patch.dict("sys.modules", {"gateway.session_context": _make_session_module(**session_vars)}):
            return build_notification_target()

    def test_slack_with_thread(self) -> None:
        mod = _make_session_module(
            HERMES_SESSION_PLATFORM="slack",
            HERMES_SESSION_CHAT_ID="C1234567890",
            HERMES_SESSION_THREAD_ID="1712345678.100200",
        )
        with patch.dict("sys.modules", {"gateway.session_context": mod}):
            target = build_notification_target()
        self.assertEqual(target, "slack:C1234567890:1712345678.100200")

    def test_slack_without_thread(self) -> None:
        mod = _make_session_module(
            HERMES_SESSION_PLATFORM="slack",
            HERMES_SESSION_CHAT_ID="C1234567890",
            HERMES_SESSION_THREAD_ID="",
        )
        with patch.dict("sys.modules", {"gateway.session_context": mod}):
            target = build_notification_target()
        self.assertEqual(target, "slack:C1234567890")

    def test_telegram_with_topic(self) -> None:
        mod = _make_session_module(
            HERMES_SESSION_PLATFORM="telegram",
            HERMES_SESSION_CHAT_ID="-1001234567890",
            HERMES_SESSION_THREAD_ID="17585",
        )
        with patch.dict("sys.modules", {"gateway.session_context": mod}):
            target = build_notification_target()
        self.assertEqual(target, "telegram:-1001234567890:17585")

    def test_discord_channel(self) -> None:
        mod = _make_session_module(
            HERMES_SESSION_PLATFORM="discord",
            HERMES_SESSION_CHAT_ID="999888777",
            HERMES_SESSION_THREAD_ID="",
        )
        with patch.dict("sys.modules", {"gateway.session_context": mod}):
            target = build_notification_target()
        self.assertEqual(target, "discord:999888777")

    def test_signal_number(self) -> None:
        mod = _make_session_module(
            HERMES_SESSION_PLATFORM="signal",
            HERMES_SESSION_CHAT_ID="+15559876543",
            HERMES_SESSION_THREAD_ID="",
        )
        with patch.dict("sys.modules", {"gateway.session_context": mod}):
            target = build_notification_target()
        self.assertEqual(target, "signal:+15559876543")

    def test_matrix_room(self) -> None:
        mod = _make_session_module(
            HERMES_SESSION_PLATFORM="matrix",
            HERMES_SESSION_CHAT_ID="!room:server.org",
            HERMES_SESSION_THREAD_ID="",
        )
        with patch.dict("sys.modules", {"gateway.session_context": mod}):
            target = build_notification_target()
        self.assertEqual(target, "matrix:!room:server.org")

    def test_cli_platform_returns_empty(self) -> None:
        mod = _make_session_module(
            HERMES_SESSION_PLATFORM="cli",
            HERMES_SESSION_CHAT_ID="some-id",
        )
        with patch.dict("sys.modules", {"gateway.session_context": mod}):
            target = build_notification_target()
        self.assertEqual(target, "")

    def test_cron_platform_returns_empty(self) -> None:
        mod = _make_session_module(
            HERMES_SESSION_PLATFORM="cron",
            HERMES_SESSION_CHAT_ID="some-id",
        )
        with patch.dict("sys.modules", {"gateway.session_context": mod}):
            target = build_notification_target()
        self.assertEqual(target, "")

    def test_empty_platform_returns_empty(self) -> None:
        mod = _make_session_module(
            HERMES_SESSION_PLATFORM="",
            HERMES_SESSION_CHAT_ID="some-id",
        )
        with patch.dict("sys.modules", {"gateway.session_context": mod}):
            target = build_notification_target()
        self.assertEqual(target, "")

    def test_missing_chat_id_returns_empty(self) -> None:
        mod = _make_session_module(
            HERMES_SESSION_PLATFORM="slack",
            HERMES_SESSION_CHAT_ID="",
        )
        with patch.dict("sys.modules", {"gateway.session_context": mod}):
            target = build_notification_target()
        self.assertEqual(target, "")

    def test_gateway_import_failure_returns_empty(self) -> None:
        # Simulate gateway not available (e.g., running in unit test without Hermes)
        with patch.dict("sys.modules", {"gateway": None, "gateway.session_context": None}):
            target = build_notification_target()
        self.assertEqual(target, "")

    def test_platform_case_insensitive(self) -> None:
        mod = _make_session_module(
            HERMES_SESSION_PLATFORM="SLACK",
            HERMES_SESSION_CHAT_ID="C123",
            HERMES_SESSION_THREAD_ID="",
        )
        with patch.dict("sys.modules", {"gateway.session_context": mod}):
            target = build_notification_target()
        self.assertEqual(target, "slack:C123")


class NotifyUserTests(unittest.TestCase):
    def _notify_with_target(self, target: str, dispatch=None) -> Mock:
        dispatch = dispatch or _make_dispatch()
        with patch("hermes.notification.build_notification_target", return_value=target):
            notify_user(dispatch, "Test message")
        return dispatch

    def test_sends_to_correct_target(self) -> None:
        dispatch = self._notify_with_target("slack:C1234:thread1")
        dispatch.assert_called_once_with(
            "send_message",
            {"target": "slack:C1234:thread1", "message": "[AMP]\nTest message"},
        )

    def test_no_op_when_notifications_disabled(self) -> None:
        dispatch = _make_dispatch()
        with patch("hermes.notification.build_notification_target", return_value="slack:C1234"):
            notify_user(dispatch, "message", notifications_enabled=False)
        dispatch.assert_not_called()

    def test_no_op_when_dispatch_tool_is_none(self) -> None:
        # Should not raise even with no dispatch_tool
        with patch("hermes.notification.build_notification_target", return_value="slack:C1234"):
            notify_user(None, "message")  # should be a no-op

    def test_no_op_when_dispatch_tool_is_not_callable(self) -> None:
        with patch("hermes.notification.build_notification_target", return_value="slack:C1234"):
            notify_user("not-a-callable", "message")  # should be a no-op

    def test_no_op_in_cli_mode(self) -> None:
        dispatch = _make_dispatch()
        with patch("hermes.notification.build_notification_target", return_value=""):
            notify_user(dispatch, "message")
        dispatch.assert_not_called()

    def test_delivery_failure_does_not_raise(self) -> None:
        dispatch = Mock(side_effect=RuntimeError("network error"))
        with patch("hermes.notification.build_notification_target", return_value="slack:C123"):
            notify_user(dispatch, "message")  # should not raise

    def test_error_in_response_is_logged_not_raised(self) -> None:
        dispatch = _make_dispatch({"error": "channel not found"})
        with patch("hermes.notification.build_notification_target", return_value="slack:C999"):
            notify_user(dispatch, "message")  # should not raise

    def test_message_prefix(self) -> None:
        dispatch = _make_dispatch()
        with patch("hermes.notification.build_notification_target", return_value="telegram:123"):
            notify_user(dispatch, "Waiting for approval.")
        _, kwargs = dispatch.call_args
        args = dispatch.call_args[0]
        self.assertTrue(args[1]["message"].startswith("[AMP]\n"))

    def test_non_string_response_handled(self) -> None:
        dispatch = Mock(return_value={"success": True})
        with patch("hermes.notification.build_notification_target", return_value="slack:C123"):
            notify_user(dispatch, "message")  # should not raise

    def test_none_response_handled(self) -> None:
        dispatch = Mock(return_value=None)
        with patch("hermes.notification.build_notification_target", return_value="slack:C123"):
            notify_user(dispatch, "message")  # should not raise


def _make_session_module(**vars) -> object:
    """Build a minimal mock for gateway.session_context."""

    class FakeModule:
        @staticmethod
        def get_session_env(name, default=""):
            return vars.get(name, default)

    return FakeModule()


if __name__ == "__main__":
    unittest.main()
