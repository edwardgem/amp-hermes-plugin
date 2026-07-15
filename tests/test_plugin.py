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


# ---------------------------------------------------------------------------
# Freshness routing (unchanged from original tests)
# ---------------------------------------------------------------------------

class FreshnessRoutingTests(unittest.TestCase):
    def test_detects_time_sensitive_market_query(self) -> None:
        self.assertTrue(_needs_live_web_search("How did the US market perform today?"))

    def test_detects_yesterday_market_query(self) -> None:
        self.assertTrue(_needs_live_web_search("How does the market in China and HK perform yesterday?"))

    def test_detects_last_week_market_query(self) -> None:
        self.assertTrue(_needs_live_web_search("How did the US market perform last week?"))

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


# ---------------------------------------------------------------------------
# Notification bridge (updated from Slack-only to platform-neutral)
# ---------------------------------------------------------------------------

class NotificationBridgeTests(unittest.TestCase):
    """Tests for the platform-neutral notification bridge."""

    def _make_plugin_with_dispatch(self, return_value=None) -> tuple:
        plugin = AmpGovernancePlugin()
        dispatch = Mock(return_value=json.dumps({"success": True}) if return_value is None else json.dumps(return_value))
        plugin._dispatch_tool = dispatch
        return plugin, dispatch

    def test_notify_user_sends_to_slack_thread(self) -> None:
        plugin, dispatch = self._make_plugin_with_dispatch()
        with patch("hermes.notification.build_notification_target", return_value="slack:C1234567890:1712345678.100200"):
            plugin._notify_user("Waiting for approval.")
        dispatch.assert_called_once_with(
            "send_message",
            {
                "target": "slack:C1234567890:1712345678.100200",
                "message": "[AMP]\nWaiting for approval.",
            },
        )

    def test_notify_user_sends_to_telegram(self) -> None:
        plugin, dispatch = self._make_plugin_with_dispatch()
        with patch("hermes.notification.build_notification_target", return_value="telegram:-100123:17585"):
            plugin._notify_user("Approval required.")
        dispatch.assert_called_once_with(
            "send_message",
            {
                "target": "telegram:-100123:17585",
                "message": "[AMP]\nApproval required.",
            },
        )

    def test_notify_user_sends_to_discord(self) -> None:
        plugin, dispatch = self._make_plugin_with_dispatch()
        with patch("hermes.notification.build_notification_target", return_value="discord:999888"):
            plugin._notify_user("Review requested.")
        dispatch.assert_called_with("send_message", {"target": "discord:999888", "message": "[AMP]\nReview requested."})

    def test_notify_user_is_noop_in_cli_mode(self) -> None:
        plugin, dispatch = self._make_plugin_with_dispatch()
        with patch("hermes.notification.build_notification_target", return_value=""):
            plugin._notify_user("Should not send.")
        dispatch.assert_not_called()

    def test_notify_user_is_noop_when_dispatch_missing(self) -> None:
        plugin = AmpGovernancePlugin()
        plugin._dispatch_tool = None
        with patch("hermes.notification.build_notification_target", return_value="slack:C123"):
            plugin._notify_user("Should not send.")  # must not raise

    def test_notify_user_failure_does_not_raise(self) -> None:
        plugin = AmpGovernancePlugin()
        plugin._dispatch_tool = Mock(side_effect=RuntimeError("channel gone"))
        with patch("hermes.notification.build_notification_target", return_value="slack:C123"):
            plugin._notify_user("message")  # must not raise

    def test_notify_user_disabled_when_notifications_off(self) -> None:
        plugin = AmpGovernancePlugin()
        plugin._dispatch_tool = Mock(return_value=json.dumps({"success": True}))
        # Override config with notifications_enabled=False
        plugin._config = SimpleNamespace(notifications_enabled=False)
        with patch("hermes.notification.build_notification_target", return_value="slack:C123"):
            plugin._notify_user("Should not send.")
        plugin._dispatch_tool.assert_not_called()

    # Regression: existing Slack HITL notification behavior is preserved
    def test_pending_hitl_sends_waiting_notification(self) -> None:
        plugin = AmpGovernancePlugin()
        plugin._notify_user = Mock()
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
        plugin._notify_user.assert_any_call(
            'AMP is waiting for a human reviewer to approve "web_search" before continuing. '
            "This action is paused pending review."
        )
        plugin._notify_user.assert_any_call('AMP review approved "web_search". Continuing now.')

    def test_rejected_hitl_sends_rejection_notification(self) -> None:
        plugin = AmpGovernancePlugin()
        plugin._notify_user = Mock()
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
        plugin._notify_user.assert_any_call('AMP reviewer rejected "terminal". Need human review')

    def test_timeout_hitl_sends_timeout_notification(self) -> None:
        plugin = AmpGovernancePlugin()
        plugin._notify_user = Mock()
        plugin._client.request_hitl = Mock(return_value={"status": "pending", "workitem_id": "w1"})
        # Decision never becomes complete
        plugin._client.get_hitl_decision = Mock(return_value={"status": "pending"})
        plugin._config = SimpleNamespace(
            hitl_timeout_minutes=0,  # immediate timeout
            hitl_poll_interval_seconds=0,
            username="tester",
            fail_closed=True,
            agent_name="amp-test",
        )
        action = NormalizedAction("terminal", "exec", "exec", {"command": "ls"})
        with patch.object(plugin, "_safe_log"), patch("time.sleep", return_value=None):
            result = plugin._evaluate_governance("inst-1", action)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["action"], "block")
        self.assertIn("timed out", result["message"])
        plugin._notify_user.assert_any_call(
            'AMP review timed out for "terminal". The action was blocked.'
        )


# ---------------------------------------------------------------------------
# Tool governance (existing behavior must be unchanged)
# ---------------------------------------------------------------------------

class ToolGovernanceRegressionTests(unittest.TestCase):
    def test_pre_tool_call_blocks_on_no_policy(self) -> None:
        plugin = AmpGovernancePlugin()
        plugin._client.request_hitl = Mock(return_value={"status": "no_policy"})
        plugin._config = SimpleNamespace(
            is_configured=True,
            fail_closed=True,
            agent_name="amp-test",
            username="tester",
            hitl_timeout_minutes=1,
            hitl_poll_interval_seconds=0,
            notifications_enabled=False,
            llm_governance_enabled=False,
        )
        with patch.object(plugin, "_ensure_instance", return_value="inst-1"), \
             patch.object(plugin, "_safe_log"):
            result = plugin.pre_tool_call(
                tool_name="terminal",
                args={"command": "ls"},
                session_id="sess-1",
            )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["action"], "block")

    def test_pre_tool_call_allows_on_no_hitl(self) -> None:
        plugin = AmpGovernancePlugin()
        plugin._client.request_hitl = Mock(return_value={"status": "no-hitl"})
        plugin._config = SimpleNamespace(
            is_configured=True,
            fail_closed=True,
            agent_name="amp-test",
            username="tester",
            hitl_timeout_minutes=1,
            hitl_poll_interval_seconds=0,
            notifications_enabled=False,
            llm_governance_enabled=False,
        )
        with patch.object(plugin, "_ensure_instance", return_value="inst-1"), \
             patch.object(plugin, "_safe_log"):
            result = plugin.pre_tool_call(
                tool_name="terminal",
                args={"command": "ls"},
                session_id="sess-1",
            )
        self.assertIsNone(result)

    def test_ungoverned_tool_is_ignored(self) -> None:
        plugin = AmpGovernancePlugin()
        plugin._client.request_hitl = Mock()
        plugin._config = SimpleNamespace(
            is_configured=True,
            fail_closed=True,
            llm_governance_enabled=False,
        )
        result = plugin.pre_tool_call(
            tool_name="send_message",
            args={"target": "slack:C123", "message": "hi"},
            session_id="sess-1",
        )
        self.assertIsNone(result)
        plugin._client.request_hitl.assert_not_called()

    def test_transform_llm_output_replaces_blocked_turn(self) -> None:
        plugin = AmpGovernancePlugin()
        plugin._blocked_turn_messages["sess-1"] = "blocked reason"
        result = plugin.transform_llm_output(response_text="original", session_id="sess-1")
        self.assertEqual(result, "This request is blocked by AMP governance. No action was taken.")

    def test_transform_llm_output_passthrough_when_not_blocked(self) -> None:
        plugin = AmpGovernancePlugin()
        result = plugin.transform_llm_output(response_text="normal response", session_id="sess-1")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# LLM observation (Phase 2A)
# ---------------------------------------------------------------------------

class LlmObservationTests(unittest.TestCase):
    def _make_plugin(self, llm_governance_enabled: bool = True) -> AmpGovernancePlugin:
        plugin = AmpGovernancePlugin()
        plugin._config = SimpleNamespace(
            is_configured=True,
            llm_governance_enabled=llm_governance_enabled,
            notifications_enabled=False,
            fail_closed=True,
            agent_name="amp-test",
            username="tester",
        )
        # Silence AMP client calls
        plugin._client.log = Mock()
        plugin._client.log_llm_event = Mock()
        plugin._client.log_execution_summary = Mock()
        return plugin

    def _start_session(self, plugin: AmpGovernancePlugin, session_id: str, instance_id: str = "inst-1") -> None:
        plugin._exec_contexts.create(session_id, instance_id, model="claude-opus-4-8", platform="slack")

    def _make_usage(self, **overrides) -> dict:
        base = {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
        }
        base.update(overrides)
        return base

    def test_hook_skipped_when_disabled(self) -> None:
        plugin = self._make_plugin(llm_governance_enabled=False)
        self._start_session(plugin, "sess-1")
        plugin.post_api_request(
            session_id="sess-1",
            model="claude-opus-4-8",
            provider="anthropic",
            usage=self._make_usage(),
        )
        ctx = plugin._exec_contexts.get("sess-1")
        assert ctx is not None
        self.assertEqual(ctx.llm_calls, 0)  # nothing accumulated

    def test_single_call_accumulates_tokens(self) -> None:
        plugin = self._make_plugin()
        self._start_session(plugin, "sess-1")
        plugin.post_api_request(
            session_id="sess-1",
            api_request_id="req-1",
            model="claude-opus-4-8",
            provider="anthropic",
            base_url="",
            api_call_count=1,
            api_duration=1.2,
            usage=self._make_usage(input_tokens=200, output_tokens=80),
        )
        ctx = plugin._exec_contexts.get("sess-1")
        assert ctx is not None
        self.assertEqual(ctx.input_tokens, 200)
        self.assertEqual(ctx.output_tokens, 80)
        self.assertEqual(ctx.llm_calls, 1)

    def test_multi_turn_accumulates_across_calls(self) -> None:
        plugin = self._make_plugin()
        self._start_session(plugin, "sess-1")
        for i in range(3):
            plugin.post_api_request(
                session_id="sess-1",
                api_request_id=f"req-{i}",
                api_call_count=i + 1,
                model="claude-opus-4-8",
                provider="anthropic",
                usage=self._make_usage(input_tokens=100, output_tokens=50),
            )
        ctx = plugin._exec_contexts.get("sess-1")
        assert ctx is not None
        self.assertEqual(ctx.input_tokens, 300)
        self.assertEqual(ctx.output_tokens, 150)
        self.assertEqual(ctx.llm_calls, 3)

    def test_none_usage_records_unknown_cost(self) -> None:
        plugin = self._make_plugin()
        self._start_session(plugin, "sess-1")
        plugin.post_api_request(
            session_id="sess-1",
            model="local-model",
            provider="ollama",
            usage=None,
        )
        ctx = plugin._exec_contexts.get("sess-1")
        assert ctx is not None
        self.assertEqual(ctx.llm_calls, 1)
        self.assertEqual(ctx.input_tokens, 0)
        self.assertEqual(ctx.output_tokens, 0)
        self.assertEqual(ctx.cost_status, "unknown")
        self.assertEqual(ctx.total_cost_usd, 0.0)

    def test_cache_tokens_accumulated(self) -> None:
        plugin = self._make_plugin()
        self._start_session(plugin, "sess-1")
        plugin.post_api_request(
            session_id="sess-1",
            model="claude-opus-4-8",
            provider="anthropic",
            usage=self._make_usage(
                input_tokens=100,
                cache_read_tokens=500,
                cache_write_tokens=200,
            ),
        )
        ctx = plugin._exec_contexts.get("sess-1")
        assert ctx is not None
        self.assertEqual(ctx.cache_read_tokens, 500)
        self.assertEqual(ctx.cache_write_tokens, 200)

    def test_reasoning_tokens_accumulated(self) -> None:
        plugin = self._make_plugin()
        self._start_session(plugin, "sess-1")
        plugin.post_api_request(
            session_id="sess-1",
            model="claude-opus-4-8",
            provider="anthropic",
            usage=self._make_usage(reasoning_tokens=150),
        )
        ctx = plugin._exec_contexts.get("sess-1")
        assert ctx is not None
        self.assertEqual(ctx.reasoning_tokens, 150)

    def test_retry_records_separate_calls(self) -> None:
        plugin = self._make_plugin()
        self._start_session(plugin, "sess-1")
        for i in range(2):
            plugin.post_api_request(
                session_id="sess-1",
                api_request_id=f"req-attempt-{i}",
                api_call_count=i + 1,
                model="claude-opus-4-8",
                provider="anthropic",
                usage=self._make_usage(input_tokens=50),
            )
        ctx = plugin._exec_contexts.get("sess-1")
        assert ctx is not None
        self.assertEqual(ctx.llm_calls, 2)
        self.assertEqual(len(ctx.llm_call_records), 2)
        self.assertEqual(ctx.input_tokens, 100)

    def test_concurrent_sessions_are_isolated(self) -> None:
        plugin = self._make_plugin()
        import threading

        sessions = ["sess-a", "sess-b", "sess-c"]
        for sid in sessions:
            plugin._exec_contexts.create(sid, f"inst-{sid}")

        errors = []

        def worker(sid: str, token_count: int) -> None:
            try:
                for _ in range(5):
                    plugin.post_api_request(
                        session_id=sid,
                        model="m",
                        provider="p",
                        usage=self._make_usage(input_tokens=token_count),
                    )
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(sid, i * 10))
            for i, sid in enumerate(sessions, start=1)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertFalse(errors)
        for i, sid in enumerate(sessions, start=1):
            ctx = plugin._exec_contexts.get(sid)
            assert ctx is not None
            self.assertEqual(ctx.input_tokens, i * 10 * 5)

    def test_amp_log_called_per_llm_call(self) -> None:
        plugin = self._make_plugin()
        self._start_session(plugin, "sess-1")
        plugin.post_api_request(
            session_id="sess-1",
            model="claude-opus-4-8",
            provider="anthropic",
            usage=self._make_usage(),
        )
        plugin._client.log_llm_event.assert_called_once()

    def test_amp_log_failure_does_not_propagate(self) -> None:
        plugin = self._make_plugin()
        plugin._client.log_llm_event = Mock(side_effect=Exception("AMP unavailable"))
        self._start_session(plugin, "sess-1")
        plugin.post_api_request(
            session_id="sess-1",
            model="claude-opus-4-8",
            provider="anthropic",
            usage=self._make_usage(),
        )  # must not raise
        ctx = plugin._exec_contexts.get("sess-1")
        assert ctx is not None
        self.assertEqual(ctx.llm_calls, 1)  # accumulation still happened

    def test_no_context_for_session_is_ignored(self) -> None:
        plugin = self._make_plugin()
        # Do not create context for this session
        plugin.post_api_request(
            session_id="sess-no-context",
            model="claude-opus-4-8",
            provider="anthropic",
            usage=self._make_usage(),
        )  # must not raise

    def test_tool_call_counter_incremented_for_governed_tools(self) -> None:
        plugin = self._make_plugin()
        self._start_session(plugin, "sess-1")
        plugin._store.get = Mock(return_value=SimpleNamespace(
            instance_id="inst-1",
            session_id="sess-1",
            model="m",
            platform="slack",
        ))
        plugin._safe_log = Mock()
        plugin.post_tool_call(
            tool_name="terminal",
            args={"command": "ls"},
            session_id="sess-1",
            status="success",
        )
        ctx = plugin._exec_contexts.get("sess-1")
        assert ctx is not None
        self.assertEqual(ctx.tool_calls, 1)

    def test_tool_call_counter_not_incremented_for_ungoverned_tools(self) -> None:
        plugin = self._make_plugin()
        self._start_session(plugin, "sess-1")
        plugin.post_tool_call(
            tool_name="send_message",
            args={"target": "slack:C123", "message": "hi"},
            session_id="sess-1",
            status="success",
        )
        ctx = plugin._exec_contexts.get("sess-1")
        assert ctx is not None
        self.assertEqual(ctx.tool_calls, 0)

    def test_session_finalize_logs_summary_and_cleans_up(self) -> None:
        plugin = self._make_plugin()
        plugin._store.get = Mock(return_value=SimpleNamespace(instance_id="inst-1"))
        plugin._store.delete = Mock()
        plugin._client.set_state = Mock()
        plugin._safe_log = Mock()
        self._start_session(plugin, "sess-1")
        plugin.post_api_request(
            session_id="sess-1",
            model="m",
            provider="p",
            usage=self._make_usage(input_tokens=500),
        )
        plugin.on_session_finalize(session_id="sess-1", reason="done")
        # ExecutionContext removed
        self.assertIsNone(plugin._exec_contexts.get("sess-1"))
        # Summary logged
        plugin._client.log_execution_summary.assert_called_once()
        summary = plugin._client.log_execution_summary.call_args[0][1]
        self.assertEqual(summary["input_tokens"], 500)
        self.assertEqual(summary["status"], "finished")

    def test_session_finalize_cleans_up_even_when_summary_log_fails(self) -> None:
        plugin = self._make_plugin()
        plugin._client.log_execution_summary = Mock(side_effect=Exception("AMP down"))
        plugin._store.get = Mock(return_value=SimpleNamespace(instance_id="inst-1"))
        plugin._store.delete = Mock()
        plugin._client.set_state = Mock()
        plugin._safe_log = Mock()
        self._start_session(plugin, "sess-1")
        plugin.on_session_finalize(session_id="sess-1", reason="done")
        self.assertIsNone(plugin._exec_contexts.get("sess-1"))  # still cleaned up


if __name__ == "__main__":
    unittest.main()
