from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
ROOT_PARENT = ROOT.parent
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from hermes.execution_context import (
    ExecutionContext,
    ExecutionContextStore,
    LlmCallRecord,
    _COST_STATUS_RANK,
)


def _make_record(**overrides) -> LlmCallRecord:
    defaults = dict(
        api_request_id="req-1",
        api_call_number=1,
        model="claude-opus-4-8",
        provider="anthropic",
        input_tokens=100,
        output_tokens=50,
        cache_read_tokens=0,
        cache_write_tokens=0,
        reasoning_tokens=0,
        cost_usd=0.001,
        cost_status="estimated",
        cost_source="official_docs_snapshot",
        api_duration=1.5,
    )
    defaults.update(overrides)
    return LlmCallRecord(**defaults)


class LlmCallRecordTests(unittest.TestCase):
    def test_total_tokens_sums_all_fields(self) -> None:
        r = _make_record(
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=200,
            cache_write_tokens=10,
            reasoning_tokens=20,
        )
        self.assertEqual(r.total_tokens, 380)

    def test_to_dict_includes_all_fields(self) -> None:
        r = _make_record()
        d = r.to_dict()
        for key in (
            "api_request_id", "api_call_number", "model", "provider",
            "input_tokens", "output_tokens", "cache_read_tokens",
            "cache_write_tokens", "reasoning_tokens", "total_tokens",
            "cost_usd", "cost_status", "cost_source", "api_duration", "timestamp",
        ):
            self.assertIn(key, d)

    def test_to_dict_total_tokens_matches_property(self) -> None:
        r = _make_record(input_tokens=300, output_tokens=100)
        self.assertEqual(r.to_dict()["total_tokens"], r.total_tokens)

    def test_timestamp_is_set_automatically(self) -> None:
        r = _make_record()
        self.assertTrue(r.timestamp, "timestamp should not be empty")
        self.assertIn("T", r.timestamp)  # ISO 8601 format


class ExecutionContextTests(unittest.TestCase):
    def _make_ctx(self) -> ExecutionContext:
        return ExecutionContext("sess-1", "inst-1", model="claude-opus-4-8", platform="slack")

    def test_initial_state(self) -> None:
        ctx = self._make_ctx()
        self.assertEqual(ctx.session_id, "sess-1")
        self.assertEqual(ctx.instance_id, "inst-1")
        self.assertEqual(ctx.model, "claude-opus-4-8")
        self.assertEqual(ctx.platform, "slack")
        self.assertEqual(ctx.input_tokens, 0)
        self.assertEqual(ctx.output_tokens, 0)
        self.assertEqual(ctx.cache_read_tokens, 0)
        self.assertEqual(ctx.cache_write_tokens, 0)
        self.assertEqual(ctx.reasoning_tokens, 0)
        self.assertEqual(ctx.total_cost_usd, 0.0)
        self.assertEqual(ctx.cost_status, "unknown")
        self.assertEqual(ctx.llm_calls, 0)
        self.assertEqual(ctx.tool_calls, 0)
        self.assertEqual(ctx.status, "running")
        self.assertTrue(ctx.execution_id, "execution_id should be a non-empty UUID")

    def test_execution_id_is_unique_per_instance(self) -> None:
        ctx1 = ExecutionContext("s1", "i1")
        ctx2 = ExecutionContext("s2", "i2")
        self.assertNotEqual(ctx1.execution_id, ctx2.execution_id)

    def test_accumulate_single_record(self) -> None:
        ctx = self._make_ctx()
        r = _make_record(
            input_tokens=100, output_tokens=50,
            cache_read_tokens=200, cache_write_tokens=10, reasoning_tokens=5,
            cost_usd=0.002, cost_status="estimated", cost_source="official_docs_snapshot",
        )
        ctx.accumulate(r)
        self.assertEqual(ctx.input_tokens, 100)
        self.assertEqual(ctx.output_tokens, 50)
        self.assertEqual(ctx.cache_read_tokens, 200)
        self.assertEqual(ctx.cache_write_tokens, 10)
        self.assertEqual(ctx.reasoning_tokens, 5)
        self.assertAlmostEqual(ctx.total_cost_usd, 0.002)
        self.assertEqual(ctx.llm_calls, 1)
        self.assertEqual(len(ctx.llm_call_records), 1)
        self.assertEqual(ctx.cost_status, "estimated")

    def test_accumulate_multiple_records_sums_correctly(self) -> None:
        ctx = self._make_ctx()
        for i in range(3):
            ctx.accumulate(_make_record(
                api_call_number=i + 1,
                input_tokens=100, output_tokens=50,
                cost_usd=0.001, cost_status="estimated", cost_source="snap",
            ))
        self.assertEqual(ctx.input_tokens, 300)
        self.assertEqual(ctx.output_tokens, 150)
        self.assertAlmostEqual(ctx.total_cost_usd, 0.003)
        self.assertEqual(ctx.llm_calls, 3)

    def test_total_tokens_property(self) -> None:
        ctx = self._make_ctx()
        ctx.accumulate(_make_record(
            input_tokens=100, output_tokens=50,
            cache_read_tokens=200, cache_write_tokens=10, reasoning_tokens=5,
        ))
        self.assertEqual(ctx.total_tokens, 365)

    def test_cost_status_worst_case_unknown_wins(self) -> None:
        ctx = self._make_ctx()
        ctx.accumulate(_make_record(cost_status="estimated", cost_source="snap"))
        self.assertEqual(ctx.cost_status, "estimated")
        ctx.accumulate(_make_record(cost_status="unknown", cost_source=""))
        self.assertEqual(ctx.cost_status, "unknown")

    def test_cost_status_actual_is_not_downgraded_by_estimated(self) -> None:
        ctx = self._make_ctx()
        ctx.accumulate(_make_record(cost_status="actual", cost_source="provider"))
        self.assertEqual(ctx.cost_status, "actual")
        ctx.accumulate(_make_record(cost_status="estimated", cost_source="snap"))
        # estimated > actual in rank, so status upgrades to estimated (worse)
        self.assertEqual(ctx.cost_status, "estimated")

    def test_cost_status_included_beats_estimated(self) -> None:
        ctx = self._make_ctx()
        ctx.accumulate(_make_record(cost_status="estimated", cost_source="snap"))
        ctx.accumulate(_make_record(cost_status="included", cost_source="provider"))
        self.assertEqual(ctx.cost_status, "included")

    def test_no_usage_record_keeps_unknown_status(self) -> None:
        ctx = self._make_ctx()
        # Record with cost_status="unknown" (provider didn't report tokens)
        ctx.accumulate(_make_record(
            input_tokens=0, output_tokens=0,
            cost_usd=0.0, cost_status="unknown", cost_source="",
        ))
        self.assertEqual(ctx.cost_status, "unknown")
        self.assertEqual(ctx.total_cost_usd, 0.0)

    def test_to_summary_dict_keys(self) -> None:
        ctx = self._make_ctx()
        ctx.accumulate(_make_record())
        s = ctx.to_summary_dict()
        for key in (
            "execution_id", "session_id", "instance_id", "model", "platform",
            "created_at", "input_tokens", "output_tokens", "cache_read_tokens",
            "cache_write_tokens", "reasoning_tokens", "total_tokens",
            "total_cost_usd", "cost_status", "cost_source", "llm_calls",
            "tool_calls", "status",
        ):
            self.assertIn(key, s, f"missing key: {key}")

    def test_to_summary_dict_values_reflect_accumulation(self) -> None:
        ctx = self._make_ctx()
        ctx.accumulate(_make_record(input_tokens=400, output_tokens=100, cost_usd=0.004))
        ctx.tool_calls = 2
        s = ctx.to_summary_dict()
        self.assertEqual(s["input_tokens"], 400)
        self.assertEqual(s["output_tokens"], 100)
        self.assertEqual(s["llm_calls"], 1)
        self.assertEqual(s["tool_calls"], 2)
        self.assertAlmostEqual(s["total_cost_usd"], 0.004, places=7)

    def test_initial_plan_governance_fields(self) -> None:
        ctx = self._make_ctx()
        self.assertIsNone(ctx.last_plan_projected_cost_usd)
        self.assertEqual(ctx.last_plan_projected_cost_status, "unknown")
        self.assertEqual(ctx.plan_approvals_count, 0)
        self.assertEqual(ctx.last_provider, "")
        self.assertEqual(ctx.last_base_url, "")

    def test_to_summary_dict_omits_plan_projected_cost_when_unset(self) -> None:
        ctx = self._make_ctx()
        s = ctx.to_summary_dict()
        self.assertNotIn("plan_projected_cost_usd", s)
        self.assertNotIn("plan_projected_cost_status", s)
        self.assertEqual(s["plan_approvals_count"], 0)

    def test_to_summary_dict_includes_plan_projected_cost_when_set(self) -> None:
        ctx = self._make_ctx()
        ctx.last_plan_projected_cost_usd = 0.03
        ctx.last_plan_projected_cost_status = "estimated"
        ctx.plan_approvals_count = 1
        s = ctx.to_summary_dict()
        self.assertAlmostEqual(s["plan_projected_cost_usd"], 0.03, places=7)
        self.assertEqual(s["plan_projected_cost_status"], "estimated")
        self.assertEqual(s["plan_approvals_count"], 1)


class ExecutionContextStoreTests(unittest.TestCase):
    def test_create_and_get(self) -> None:
        store = ExecutionContextStore()
        ctx = store.create("sess-1", "inst-1", model="m", platform="slack")
        self.assertIsNotNone(ctx)
        self.assertEqual(store.get("sess-1"), ctx)

    def test_get_missing_returns_none(self) -> None:
        store = ExecutionContextStore()
        self.assertIsNone(store.get("nonexistent"))

    def test_remove_returns_context_and_clears_it(self) -> None:
        store = ExecutionContextStore()
        store.create("sess-1", "inst-1")
        removed = store.remove("sess-1")
        self.assertIsNotNone(removed)
        self.assertIsNone(store.get("sess-1"))

    def test_remove_missing_returns_none(self) -> None:
        store = ExecutionContextStore()
        self.assertIsNone(store.remove("nonexistent"))

    def test_len(self) -> None:
        store = ExecutionContextStore()
        self.assertEqual(len(store), 0)
        store.create("s1", "i1")
        store.create("s2", "i2")
        self.assertEqual(len(store), 2)
        store.remove("s1")
        self.assertEqual(len(store), 1)

    def test_concurrent_creates_are_isolated(self) -> None:
        store = ExecutionContextStore()
        results = {}
        errors = []

        def worker(session_id: str) -> None:
            try:
                ctx = store.create(session_id, f"inst-{session_id}")
                ctx.accumulate(_make_record(input_tokens=100))
                results[session_id] = ctx.input_tokens
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(f"sess-{i}",)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertFalse(errors, f"Errors in threads: {errors}")
        self.assertEqual(len(store), 20)
        for session_id, tokens in results.items():
            self.assertEqual(tokens, 100, f"session {session_id} has wrong token count")

    def test_cleanup_after_remove(self) -> None:
        store = ExecutionContextStore()
        for i in range(100):
            store.create(f"sess-{i}", f"inst-{i}")
        for i in range(100):
            store.remove(f"sess-{i}")
        self.assertEqual(len(store), 0)


if __name__ == "__main__":
    unittest.main()
