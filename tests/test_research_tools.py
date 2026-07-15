"""Tests for Phase 3B registered tools: amp_evaluate_research_plan,
amp_load_research_topics, amp_governance_summary.

These test the deterministic Python surface only — whether a model actually
loads the research-agent skill and calls these tools in the right order is
model behavior, not covered here (see the manual test procedure in the
final report).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
ROOT_PARENT = ROOT.parent
HERMES_AGENT_ROOT = Path.home() / ".hermes" / "hermes-agent"

if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))
if HERMES_AGENT_ROOT.exists() and str(HERMES_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(HERMES_AGENT_ROOT))

import hermes as mod
from hermes.execution_context import ExecutionContext


def _write_topics(tmp: str, content: str) -> str:
    path = Path(tmp) / "research_topics.yaml"
    path.write_text(content)
    return str(path)


# ---------------------------------------------------------------------------
# 1. Registration
# ---------------------------------------------------------------------------

class ToolRegistrationTests(unittest.TestCase):
    def test_register_wires_all_three_tools_and_the_skill(self):
        ctx = SimpleNamespace(
            dispatch_tool=Mock(),
            register_hook=Mock(),
            register_middleware=Mock(),
            register_tool=Mock(),
            register_skill=Mock(),
        )
        fresh_plugin = mod.AmpGovernancePlugin()
        with patch.object(mod, "_PLUGIN", fresh_plugin):
            mod.register(ctx)

        tool_names = {call.kwargs.get("name") for call in ctx.register_tool.call_args_list}
        self.assertEqual(
            tool_names,
            {"amp_evaluate_research_plan", "amp_load_research_topics", "amp_governance_summary"},
        )
        for call in ctx.register_tool.call_args_list:
            self.assertEqual(call.kwargs.get("toolset"), "amp_governance")
            self.assertTrue(callable(call.kwargs.get("handler")))
            self.assertIn("parameters", call.kwargs.get("schema"))

        ctx.register_skill.assert_called_once()
        skill_args = ctx.register_skill.call_args
        self.assertEqual(skill_args.args[0], "research-agent")
        self.assertTrue(str(skill_args.args[1]).endswith("skills/research-agent/SKILL.md"))

    def test_skill_registration_failure_does_not_crash_register(self):
        ctx = SimpleNamespace(
            dispatch_tool=Mock(),
            register_hook=Mock(),
            register_middleware=Mock(),
            register_tool=Mock(),
            register_skill=Mock(side_effect=FileNotFoundError("no SKILL.md")),
        )
        fresh_plugin = mod.AmpGovernancePlugin()
        with patch.object(mod, "_PLUGIN", fresh_plugin):
            mod.register(ctx)  # must not raise


# ---------------------------------------------------------------------------
# 2. amp_evaluate_research_plan tool
# ---------------------------------------------------------------------------

class EvaluateResearchPlanToolTests(unittest.TestCase):
    def test_missing_plan_arg_returns_error_without_calling_plugin(self):
        fake_plugin = Mock()
        with patch.object(mod, "_PLUGIN", fake_plugin):
            raw = mod._tool_amp_evaluate_research_plan({})
        result = json.loads(raw)
        self.assertEqual(result["status"], "error")
        fake_plugin.evaluate_proposed_plan.assert_not_called()

    def test_session_id_sourced_from_session_context_not_args(self):
        fake_plugin = Mock()
        fake_plugin.evaluate_proposed_plan = Mock(return_value={"status": "approved"})
        plan = {"plan_type": "research", "projected_cost_usd": 4.75}
        args = {"plan": plan, "session_id": "should-be-ignored"}

        with patch.object(mod, "_PLUGIN", fake_plugin), \
             patch.object(mod, "_current_session_id", return_value="real-session-123"):
            raw = mod._tool_amp_evaluate_research_plan(args)

        fake_plugin.evaluate_proposed_plan.assert_called_once_with("real-session-123", plan)
        self.assertEqual(json.loads(raw)["status"], "approved")

    def test_deeply_nested_payload_preserved_unmodified(self):
        fake_plugin = Mock()
        fake_plugin.evaluate_proposed_plan = Mock(return_value={"status": "approved"})
        nested_payload = {
            "topics": ["AI agent governance", "Progressive autonomy"],
            "research_depth": "standard",
            "sources_per_topic": 5,
            "nested": {"arbitrary": ["structure", 1, True, {"deep": None}]},
        }
        plan = {
            "plan_type": "research",
            "projected_cost_usd": 4.75,
            "payload": nested_payload,
        }

        with patch.object(mod, "_PLUGIN", fake_plugin), \
             patch.object(mod, "_current_session_id", return_value="s"):
            mod._tool_amp_evaluate_research_plan({"plan": plan})

        forwarded_plan = fake_plugin.evaluate_proposed_plan.call_args[0][1]
        self.assertEqual(forwarded_plan["payload"], nested_payload)

    def test_all_four_decision_statuses_pass_through_unchanged(self):
        for status in ("approved", "rejected", "timed_out", "error"):
            fake_plugin = Mock()
            decision = {
                "status": status, "plan_id": "p1", "approved_budget_usd": 4.75 if status == "approved" else None,
                "reason": "", "workitem_id": None,
            }
            fake_plugin.evaluate_proposed_plan = Mock(return_value=decision)
            with patch.object(mod, "_PLUGIN", fake_plugin), \
                 patch.object(mod, "_current_session_id", return_value="s"):
                raw = mod._tool_amp_evaluate_research_plan(
                    {"plan": {"plan_type": "research", "projected_cost_usd": 1.0}}
                )
            self.assertEqual(json.loads(raw), decision)


# ---------------------------------------------------------------------------
# 3. amp_load_research_topics tool
# ---------------------------------------------------------------------------

class LoadResearchTopicsToolTests(unittest.TestCase):
    def test_valid_path_returns_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_topics(tmp, "topics:\n  - AI agent governance\n")
            raw = mod._tool_amp_load_research_topics({"path": path})
        result = json.loads(raw)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["topics"], ["AI agent governance"])

    def test_missing_file_returns_error_not_exception(self):
        raw = mod._tool_amp_load_research_topics({"path": "/nonexistent/research_topics.yaml"})
        result = json.loads(raw)
        self.assertEqual(result["status"], "error")

    def test_default_path_used_when_omitted(self):
        with patch.object(mod, "load_research_topics") as mock_load:
            mock_load.return_value = {"topics": ["x"], "research_depth": "standard",
                                       "sources_per_topic": 5, "lookback_days": 7}
            mod._tool_amp_load_research_topics({})
        mock_load.assert_called_once_with(mod._DEFAULT_RESEARCH_TOPICS_PATH)


# ---------------------------------------------------------------------------
# 4. amp_governance_summary tool
# ---------------------------------------------------------------------------

class GovernanceSummaryToolTests(unittest.TestCase):
    def test_no_context_returns_explicit_status(self):
        with patch.object(mod, "_current_session_id", return_value="no-such-session"):
            raw = mod._tool_amp_governance_summary({})
        self.assertEqual(json.loads(raw)["status"], "no_context")

    def test_no_session_id_returns_no_context(self):
        with patch.object(mod, "_current_session_id", return_value=""):
            raw = mod._tool_amp_governance_summary({})
        self.assertEqual(json.loads(raw)["status"], "no_context")

    def test_existing_context_returns_summary_fields(self):
        exec_ctx = ExecutionContext("s", "inst-1", model="m", platform="slack")
        exec_ctx.total_cost_usd = 3.92
        exec_ctx.llm_calls = 16
        exec_ctx.tool_calls = 21
        exec_ctx.llm_hitl_approved = 0

        with patch.object(mod, "_current_session_id", return_value="s"), \
             patch.object(mod._PLUGIN._exec_contexts, "get", return_value=exec_ctx):
            raw = mod._tool_amp_governance_summary({})

        result = json.loads(raw)
        self.assertEqual(result["status"], "running")
        self.assertAlmostEqual(result["total_cost_usd"], 3.92, places=5)
        self.assertEqual(result["llm_calls"], 16)
        self.assertEqual(result["tool_calls"], 21)
        self.assertEqual(result["llm_hitl_approved"], 0)

    def test_does_not_invent_values_not_in_summary_dict(self):
        """No 'approved_budget_usd' key when it was never set (None -> omitted
        by ExecutionContext.to_summary_dict(), matching existing Phase 2B behavior)."""
        exec_ctx = ExecutionContext("s", "inst-1", model="m", platform="slack")
        with patch.object(mod, "_current_session_id", return_value="s"), \
             patch.object(mod._PLUGIN._exec_contexts, "get", return_value=exec_ctx):
            raw = mod._tool_amp_governance_summary({})
        self.assertNotIn("approved_budget_usd", json.loads(raw))


if __name__ == "__main__":
    unittest.main()
