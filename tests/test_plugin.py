from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, PropertyMock, patch

ROOT = Path(__file__).resolve().parent.parent
ROOT_PARENT = ROOT.parent
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from hermes import _build_live_search_context, _needs_live_web_search, AmpGovernancePlugin
from hermes.policy import NormalizedAction


class FreshnessRoutingTests(unittest.TestCase):
    def test_detects_time_sensitive_market_query(self) -> None:
        self.assertTrue(_needs_live_web_search("How did the US market perform today?"))

    def test_detects_explicit_web_search_request(self) -> None:
        self.assertTrue(_needs_live_web_search("Perform a web search to find social security fraud news in the US"))

    def test_ignores_non_freshness_prompt(self) -> None:
        self.assertFalse(_needs_live_web_search("Explain what a stock market index is"))

    def test_context_mentions_web_search_and_current_date(self) -> None:
        context = _build_live_search_context("How did the US market perform today?")
        self.assertIn("Current UTC date:", context)
        self.assertIn("web_search tool", context)
        self.assertIn("Do not answer from memory", context)

    def test_pre_llm_call_returns_context_for_freshness_query(self) -> None:
        plugin = AmpGovernancePlugin()
        with patch.object(type(plugin._config), "is_configured", new_callable=PropertyMock, return_value=True), \
             patch.object(plugin, "_ensure_instance", return_value="inst-1"), \
             patch.object(plugin, "_safe_log"):
            result = plugin.pre_llm_call(
                session_id="sess-1",
                user_message="How did the US market perform today?",
                model="test-model",
                platform="slack",
            )
        self.assertIsInstance(result, dict)
        assert isinstance(result, dict)
        self.assertIn("context", result)
        self.assertIn("web_search tool", result["context"])

    def test_pre_llm_call_no_context_for_non_freshness_query(self) -> None:
        plugin = AmpGovernancePlugin()
        with patch.object(type(plugin._config), "is_configured", new_callable=PropertyMock, return_value=True), \
             patch.object(plugin, "_ensure_instance", return_value="inst-1"), \
             patch.object(plugin, "_safe_log"):
            result = plugin.pre_llm_call(
                session_id="sess-1",
                user_message="Explain what a stock market index is",
                model="test-model",
                platform="slack",
            )
        self.assertIsNone(result)


class SlackNotificationTests(unittest.TestCase):
    def test_notify_slack_uses_current_chat_target(self) -> None:
        plugin = AmpGovernancePlugin()
        plugin._dispatch_tool = Mock(return_value=json.dumps({"success": True}))
        with patch.object(plugin, "_build_slack_target", return_value="slack:C1234567890:1712345678.100200"):
            plugin._notify_slack("Waiting for approval.")
        plugin._dispatch_tool.assert_called_once_with(
            "send_message",
            {
                "target": "slack:C1234567890:1712345678.100200",
                "message": "[AMP]\nWaiting for approval.",
            },
        )

    def test_pending_hitl_sends_waiting_notification(self) -> None:
        plugin = AmpGovernancePlugin()
        plugin._notify_slack = Mock()
        plugin._client.request_hitl = Mock(return_value={"status": "pending", "workitem_id": "w1"})
        plugin._client.get_hitl_decision = Mock(return_value={"status": "complete", "resolution": "approved"})
        plugin._config = SimpleNamespace(
            hitl_timeout_minutes=1,
            hitl_poll_interval_seconds=0,
            username="tester",
            fail_closed=True,
            agent_name="amp-test",
        )
        action = NormalizedAction("web_search", "exec", "web_search", {"query": "today market"})
        with patch.object(plugin, "_safe_log"), patch("time.sleep", return_value=None):
            result = plugin._evaluate_governance("inst-1", action)
        self.assertIsNone(result)
        plugin._notify_slack.assert_any_call(
            'AMP is waiting for a human reviewer to approve "web_search" before continuing. '
            "This action is paused pending review."
        )
        plugin._notify_slack.assert_any_call('AMP review approved "web_search". Continuing now.')

    def test_rejected_hitl_sends_rejection_notification(self) -> None:
        plugin = AmpGovernancePlugin()
        plugin._notify_slack = Mock()
        plugin._client.request_hitl = Mock(return_value={"status": "pending", "workitem_id": "w1"})
        plugin._client.get_hitl_decision = Mock(
            return_value={"status": "complete", "resolution": "rejected", "information": "Need human review"}
        )
        plugin._config = SimpleNamespace(
            hitl_timeout_minutes=1,
            hitl_poll_interval_seconds=0,
            username="tester",
            fail_closed=True,
            agent_name="amp-test",
        )
        action = NormalizedAction("terminal", "exec", "exec", {"command": "rm -rf /tmp/x"})
        with patch.object(plugin, "_safe_log"), patch("time.sleep", return_value=None):
            result = plugin._evaluate_governance("inst-1", action)
        self.assertEqual(
            result,
            {"action": "block", "message": "terminal was rejected by AMP HITL review. Need human review"},
        )
        plugin._notify_slack.assert_any_call('AMP reviewer rejected "terminal". Need human review')


if __name__ == "__main__":
    unittest.main()
