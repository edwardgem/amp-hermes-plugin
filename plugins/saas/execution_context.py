from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Higher rank = worse quality. Cost status is accumulated as worst-case.
_COST_STATUS_RANK: Dict[str, int] = {
    "actual": 0,
    "estimated": 1,
    "included": 2,
    "unknown": 3,
}


@dataclass
class LlmCallRecord:
    """Immutable snapshot of a single completed LLM API call."""

    api_request_id: str
    api_call_number: int
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    cost_usd: float
    cost_status: str    # "actual" | "estimated" | "included" | "unknown"
    cost_source: str
    api_duration: float
    timestamp: str = field(default_factory=_utc_now)

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
            + self.reasoning_tokens
        )

    def to_dict(self) -> dict:
        return {
            "api_request_id": self.api_request_id,
            "api_call_number": self.api_call_number,
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "cost_status": self.cost_status,
            "cost_source": self.cost_source,
            "api_duration": self.api_duration,
            "timestamp": self.timestamp,
        }


class ExecutionContext:
    """
    Per-session context accumulating LLM usage, cost, and call counts.

    Mutated by a single executor thread per session.
    Thread safety is provided by ExecutionContextStore for add/remove operations.
    """

    def __init__(
        self,
        session_id: str,
        instance_id: str,
        *,
        model: str = "",
        platform: str = "",
    ) -> None:
        self.session_id = session_id
        self.instance_id = instance_id
        self.model = model
        self.platform = platform
        self.execution_id: str = str(uuid.uuid4())
        self.created_at: str = _utc_now()
        self.status: str = "running"

        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cache_read_tokens: int = 0
        self.cache_write_tokens: int = 0
        self.reasoning_tokens: int = 0

        self.total_cost_usd: float = 0.0
        self.cost_status: str = "unknown"
        self.cost_source: str = ""

        self.llm_calls: int = 0
        self.tool_calls: int = 0

        # Most recently observed provider/base_url for this session's LLM
        # calls -- used to project research-plan cost from real pricing
        # before any call has actually happened yet (see _project_research_cost).
        self.last_provider: str = ""
        self.last_base_url: str = ""

        # Phase 2B enforcement tracking
        self.approved_budget_usd: Optional[float] = None
        self.last_policy_eval_at: Optional[str] = None
        self.last_policy_result: Optional[str] = None
        self.hitl_workitem_id: Optional[str] = None
        self.policy_eval_count: int = 0
        self.llm_hitl_approved: int = 0
        self.llm_blocked: int = 0

        # Phase 3A plan governance: the most recently *submitted* plan's
        # projected cost (set regardless of decision outcome) and a count of
        # how many plans this session has had approved. Reported alongside
        # approved_budget_usd in to_summary_dict() so amp_governance_summary
        # is a single, fresh source for every number research-agent's step 8
        # report needs -- nothing left for the model to recall from an
        # earlier turn.
        self.last_plan_projected_cost_usd: Optional[float] = None
        self.last_plan_projected_cost_status: str = "unknown"
        self.plan_approvals_count: int = 0

        self.llm_call_records: List[LlmCallRecord] = []

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
            + self.reasoning_tokens
        )

    def accumulate(self, record: LlmCallRecord) -> None:
        """Incorporate a completed LLM call into accumulated totals."""
        self.input_tokens += record.input_tokens
        self.output_tokens += record.output_tokens
        self.cache_read_tokens += record.cache_read_tokens
        self.cache_write_tokens += record.cache_write_tokens
        self.reasoning_tokens += record.reasoning_tokens
        self.total_cost_usd += record.cost_usd
        self.llm_calls += 1
        self.llm_call_records.append(record)
        # Worst-case cost status wins
        existing_rank = _COST_STATUS_RANK.get(self.cost_status, 3)
        new_rank = _COST_STATUS_RANK.get(record.cost_status, 3)
        if new_rank > existing_rank or not self.cost_source:
            self.cost_status = record.cost_status
            self.cost_source = record.cost_source

    def to_summary_dict(self) -> dict:
        d: dict = {
            "execution_id": self.execution_id,
            "session_id": self.session_id,
            "instance_id": self.instance_id,
            "model": self.model,
            "platform": self.platform,
            "created_at": self.created_at,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 8),
            "cost_status": self.cost_status,
            "cost_source": self.cost_source,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "policy_eval_count": self.policy_eval_count,
            "llm_hitl_approved": self.llm_hitl_approved,
            "llm_blocked": self.llm_blocked,
            "plan_approvals_count": self.plan_approvals_count,
            "status": self.status,
        }
        if self.approved_budget_usd is not None:
            d["approved_budget_usd"] = round(self.approved_budget_usd, 8)
        if self.last_plan_projected_cost_usd is not None:
            d["plan_projected_cost_usd"] = round(self.last_plan_projected_cost_usd, 8)
            d["plan_projected_cost_status"] = self.last_plan_projected_cost_status
        return d


class ExecutionContextStore:
    """Thread-safe in-memory store of ExecutionContext objects keyed by session_id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: Dict[str, ExecutionContext] = {}

    def create(
        self,
        session_id: str,
        instance_id: str,
        *,
        model: str = "",
        platform: str = "",
    ) -> ExecutionContext:
        ctx = ExecutionContext(session_id, instance_id, model=model, platform=platform)
        with self._lock:
            self._store[session_id] = ctx
        return ctx

    def get(self, session_id: str) -> Optional[ExecutionContext]:
        with self._lock:
            return self._store.get(session_id)

    def remove(self, session_id: str) -> Optional[ExecutionContext]:
        with self._lock:
            return self._store.pop(session_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
