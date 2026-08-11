#!/usr/bin/env python3
"""End-to-end smoke test for the AMP-governed research-agent skill.

Drives a real `hermes chat` turn (no Slack, no browser) for the ad hoc or
configured research workflow, or a plain freshness query that must *not*
trigger it, auto-approves any AMP plan-approval workitem it raises via the
same API AHP itself uses, then cross-checks the final report against
Hermes' own ground-truth session ledger (~/.hermes/state.db). Written to
catch, automatically, the exact failure modes chased manually over several
days of testing:

  - wrong skill routed (configured pointer instead of ad hoc, or vice versa)
  - a plain time-sensitive question (no "research" wording) getting diverted
    into the governed research workflow instead of a direct web_search
  - plan submitted with no real cost estimate (estimated_llm_calls missing)
  - an invented/fabricated dollar figure (the $100.00 / $85.00 bug)
  - a governance summary that doesn't match what actually happened
  - no HITL request raised at all (currently expected under the live eval
    policy -- see the "auto-approved" note in the report -- but worth
    watching for if/when a hard cost criterion gets configured)

Requires: a live Hermes gateway config (~/.hermes/.env with AMP_BACKEND_URL/
AMP_API_KEY), the amp-governance plugin installed, and real LLM credentials
-- this makes real API calls and costs real (small) money per run. Not part
of `pytest tests/`; run it directly.

Usage (use the hermes-agent venv -- it has pyyaml; plain python3 may not):
    /Users/edwardc/.hermes/hermes-agent/venv/bin/python scripts/e2e_research_test.py adhoc
    /Users/edwardc/.hermes/hermes-agent/venv/bin/python scripts/e2e_research_test.py configured
    /Users/edwardc/.hermes/hermes-agent/venv/bin/python scripts/e2e_research_test.py freshness
    /Users/edwardc/.hermes/hermes-agent/venv/bin/python scripts/e2e_research_test.py all -v
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yaml

HERMES_HOME = Path.home() / ".hermes"
STATE_DB = HERMES_HOME / "state.db"
RESEARCH_TOPICS_PATH = HERMES_HOME / "research_topics.yaml"

# Exact dollar figures observed from the LLM-invented-cost bug -- if either
# ever reappears verbatim, that's a strong signal of a regression, not
# coincidence.
BAD_COST_SENTINELS = {100.0, 85.0}
SANE_COST_CEILING_USD = 2.0

APPROVAL_POLL_INTERVAL_SECONDS = 2.0
APPROVAL_POLL_TIMEOUT_SECONDS = 90
CHAT_TIMEOUT_SECONDS = 600


# ---------------------------------------------------------------------------
# AMP API client (mirrors hermes/amp_client.py's own request pattern)
# ---------------------------------------------------------------------------

def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def load_amp_credentials() -> dict[str, str]:
    env = _read_env_file(HERMES_HOME / ".env")
    for key in ("AMP_BACKEND_URL", "AMP_API_KEY", "AMP_ORG_ID", "AMP_USERNAME"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    missing = [k for k in ("AMP_BACKEND_URL", "AMP_API_KEY") if not env.get(k)]
    if missing:
        raise SystemExit(f"Missing required AMP credentials in ~/.hermes/.env: {missing}")
    return env


class AmpApi:
    def __init__(self, backend_url: str, api_key: str):
        self.backend_url = backend_url.rstrip("/")
        self.api_key = api_key

    def _request(self, method: str, path: str, payload: Optional[dict] = None, query: Optional[dict] = None) -> Any:
        url = f"{self.backend_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = Request(
            url, data=data,
            headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8") or "{}"
                return json.loads(body)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"AMP API HTTP {exc.code} on {method} {path}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"AMP API unreachable on {method} {path}: {exc.reason}") from exc

    def list_pending_approvals(self) -> list[dict]:
        data = self._request("GET", "/api/workitems")
        items = data.get("workitems") or []
        return [
            wi for wi in items
            if str(wi.get("action") or "").strip().lower() == "approval"
            and str(wi.get("status") or "").strip().lower() == "pending"
        ]

    def approve_workitem(self, workitem_id: str) -> None:
        self._request(
            "PUT", f"/api/workitems/{workitem_id}/status",
            payload={"status": "complete", "resolution": "approve", "information": "auto-approved by e2e_research_test.py"},
        )


class ApprovalWatcher:
    """Background poller that auto-approves any new AMP plan-approval
    workitem it sees, and records what it approved for the report."""

    def __init__(self, api: AmpApi):
        self._api = api
        self._stop = threading.Event()
        self._seen: set[str] = set()
        self.approved: list[dict] = []
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, wait_seconds: float = 3.0) -> None:
        self._stop.set()
        self._thread.join(timeout=wait_seconds)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                for wi in self._api.list_pending_approvals():
                    wid = str(wi.get("workitem_id") or "")
                    if not wid or wid in self._seen:
                        continue
                    self._seen.add(wid)
                    try:
                        self._api.approve_workitem(wid)
                        self.approved.append(wi)
                    except Exception as exc:  # noqa: BLE001 - report, don't crash the watcher
                        print(f"  [approval-watcher] failed to approve {wid}: {exc}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                print(f"  [approval-watcher] poll failed: {exc}", file=sys.stderr)
            self._stop.wait(APPROVAL_POLL_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# Driving hermes chat
# ---------------------------------------------------------------------------

def run_chat(prompt: str) -> tuple[str, str]:
    """Runs one non-interactive `hermes chat` turn. Returns (session_id, final_text)."""
    proc = subprocess.run(
        ["hermes", "chat", "-q", prompt, "-Q"],
        capture_output=True, text=True, timeout=CHAT_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"hermes chat exited {proc.returncode}\nstderr: {proc.stderr}")
    final_text = proc.stdout.strip()
    # -Q prints "session_id: ..." on stderr, separate from the response on stdout.
    session_id = ""
    for line in proc.stderr.splitlines():
        if line.startswith("session_id:"):
            session_id = line.split(":", 1)[1].strip()
            break
    if not session_id:
        raise RuntimeError(
            f"Could not find session_id in hermes chat output.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return session_id, final_text


# ---------------------------------------------------------------------------
# Ground truth from ~/.hermes/state.db
# ---------------------------------------------------------------------------

def inspect_session(session_id: str) -> dict:
    conn = sqlite3.connect(str(STATE_DB))
    conn.row_factory = sqlite3.Row
    try:
        session_row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        messages = conn.execute(
            "SELECT id, role, tool_name, tool_calls FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    tool_invocations: list[tuple[str, dict]] = []
    for m in messages:
        if m["role"] != "assistant" or not m["tool_calls"]:
            continue
        try:
            calls = json.loads(m["tool_calls"])
        except (TypeError, ValueError):
            continue
        for call in calls:
            fn = call.get("function") or {}
            name = str(fn.get("name") or "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (TypeError, ValueError):
                args = {}
            tool_invocations.append((name, args))

    return {
        "session": dict(session_row) if session_row else {},
        "tool_invocations": tool_invocations,
    }


def find_calls(tool_invocations: list[tuple[str, dict]], name: str) -> list[dict]:
    return [args for (n, args) in tool_invocations if n == name]


# ---------------------------------------------------------------------------
# Report parsing + checks
# ---------------------------------------------------------------------------

class Check:
    def __init__(self, name: str, passed: bool, detail: str, severity: str = "fail"):
        self.name = name
        self.passed = passed
        self.detail = detail
        self.severity = severity  # "fail" or "warn" -- warn doesn't flip overall pass/fail

    def line(self) -> str:
        if self.passed:
            mark = "PASS"
        else:
            mark = "WARN" if self.severity == "warn" else "FAIL"
        return f"  [{mark}] {self.name}: {self.detail}"


def _extract_money(pattern: str, text: str) -> Optional[float]:
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _extract_int(pattern: str, text: str) -> Optional[int]:
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def check_governance_summary(final_text: str, ground_truth: dict) -> list[Check]:
    checks: list[Check] = []

    has_summary = "Governance summary" in final_text
    checks.append(Check("governance summary present", has_summary, "found 'Governance summary' block in final reply"))
    if not has_summary:
        return checks

    actual_cost = _extract_money(r"Actual cost:\s*\$([0-9.]+)", final_text)
    checks.append(Check(
        "actual cost is not a known-fabricated value",
        actual_cost is None or actual_cost not in BAD_COST_SENTINELS,
        f"reported actual cost = {actual_cost}",
    ))
    checks.append(Check(
        "actual cost is within a sane ceiling",
        actual_cost is None or actual_cost <= SANE_COST_CEILING_USD,
        f"reported actual cost = {actual_cost} (ceiling ${SANE_COST_CEILING_USD})",
    ))

    plan_cost = _extract_money(r"Plan projected cost:\s*\$([0-9.]+)", final_text)
    checks.append(Check(
        "plan projected cost is not a known-fabricated value",
        plan_cost is None or plan_cost not in BAD_COST_SENTINELS,
        f"reported plan projected cost = {plan_cost}",
    ))

    reported_llm_calls = _extract_int(r"LLM calls:\s*(\d+)", final_text)
    reported_tool_calls = _extract_int(r"Tool calls:\s*(\d+)", final_text)
    session = ground_truth["session"]
    real_api_calls = session.get("api_call_count")
    real_tool_calls = session.get("tool_call_count")
    if reported_llm_calls is not None and real_api_calls is not None:
        # The final response-generation call itself isn't counted yet at the
        # point amp_governance_summary runs, so allow a small gap rather
        # than requiring exact equality.
        diff = abs(reported_llm_calls - real_api_calls)
        checks.append(Check(
            "reported LLM calls roughly match state.db ground truth",
            diff <= 2,
            f"reported={reported_llm_calls} state.db api_call_count={real_api_calls} (diff={diff})",
            severity="warn",
        ))
    if reported_tool_calls is not None and real_tool_calls is not None:
        diff = abs(reported_tool_calls - real_tool_calls)
        checks.append(Check(
            "reported tool calls roughly match state.db ground truth",
            diff <= 2,
            f"reported={reported_tool_calls} state.db tool_call_count={real_tool_calls} (diff={diff})",
            severity="warn",
        ))

    return checks


def check_hitl(approved: list[dict]) -> Check:
    if approved:
        ids = ", ".join(str(a.get("workitem_id")) for a in approved)
        return Check("HITL requested", True, f"auto-approved {len(approved)} workitem(s): {ids}", severity="warn")
    return Check(
        "HITL requested", True,
        "no workitem was created -- plan auto-approved via AMP's no_hard_criteria_triggered "
        "policy path (expected under the current eval policy; configure a hard cost criterion "
        "if real human review should be required)",
        severity="warn",
    )


def check_adhoc(ground_truth: dict) -> list[Check]:
    checks: list[Check] = []
    invocations = ground_truth["tool_invocations"]

    skill_views = find_calls(invocations, "skill_view")
    skill_names = [str(a.get("name") or "") for a in skill_views]
    checks.append(Check(
        "routed straight to the real skill, not a pointer skill",
        "amp-governance:research-agent" in skill_names and "amp-research" not in skill_names,
        f"skill_view calls: {skill_names or '(none)'}",
    ))

    checks.append(Check(
        "did not load configured topics",
        not find_calls(invocations, "amp_load_research_topics"),
        f"amp_load_research_topics called {len(find_calls(invocations, 'amp_load_research_topics'))} time(s)",
    ))

    plans = find_calls(invocations, "amp_evaluate_research_plan")
    checks.append(Check("submitted exactly one plan", len(plans) == 1, f"amp_evaluate_research_plan called {len(plans)} time(s)"))
    if plans:
        plan = plans[0].get("plan") or {}
        est_calls = plan.get("estimated_llm_calls")
        checks.append(Check(
            "plan includes a positive estimated_llm_calls",
            isinstance(est_calls, int) and est_calls > 0,
            f"estimated_llm_calls = {est_calls!r}",
        ))
        topics = ((plan.get("payload") or {}).get("topics")) or []
        checks.append(Check(
            "plan topics reflect the ad hoc request",
            any("market" in str(t).lower() for t in topics),
            f"plan topics = {topics}",
        ))

    search_calls = len(find_calls(invocations, "web_search")) + len(find_calls(invocations, "web_extract"))
    checks.append(Check("actually researched something", search_calls > 0, f"{search_calls} web_search/web_extract call(s)"))

    return checks


def check_configured(ground_truth: dict) -> list[Check]:
    checks: list[Check] = []
    invocations = ground_truth["tool_invocations"]

    loads = find_calls(invocations, "amp_load_research_topics")
    checks.append(Check("loaded configured topics", len(loads) >= 1, f"amp_load_research_topics called {len(loads)} time(s)"))

    skill_views = find_calls(invocations, "skill_view")
    skill_names = [str(a.get("name") or "") for a in skill_views]
    checks.append(Check(
        "routed straight to the real skill, not a pointer skill",
        "amp-governance:research-agent" in skill_names and "amp-research-topic" not in skill_names,
        f"skill_view calls: {skill_names or '(none)'}",
    ))

    plans = find_calls(invocations, "amp_evaluate_research_plan")
    checks.append(Check("submitted exactly one plan", len(plans) == 1, f"amp_evaluate_research_plan called {len(plans)} time(s)"))
    if plans and RESEARCH_TOPICS_PATH.exists():
        plan = plans[0].get("plan") or {}
        est_calls = plan.get("estimated_llm_calls")
        checks.append(Check(
            "plan includes a positive estimated_llm_calls",
            isinstance(est_calls, int) and est_calls > 0,
            f"estimated_llm_calls = {est_calls!r}",
        ))
        configured_topics = set((yaml.safe_load(RESEARCH_TOPICS_PATH.read_text()) or {}).get("topics") or [])
        plan_topics = set(((plan.get("payload") or {}).get("topics")) or [])
        checks.append(Check(
            "plan topics match research_topics.yaml",
            configured_topics and configured_topics == plan_topics,
            f"configured={sorted(configured_topics)} plan={sorted(plan_topics)}",
        ))

    search_calls = len(find_calls(invocations, "web_search")) + len(find_calls(invocations, "web_extract"))
    checks.append(Check("actually researched something", search_calls > 0, f"{search_calls} web_search/web_extract call(s)"))

    return checks


def check_freshness(ground_truth: dict) -> list[Check]:
    """A plain time-sensitive question (no 'research' wording) must go
    straight to Hermes' native web_search -- it must never be diverted into
    the governed research workflow, which would make a routine weather/price
    question wait on a plan-approval round trip it doesn't need."""
    checks: list[Check] = []
    invocations = ground_truth["tool_invocations"]

    skill_views = find_calls(invocations, "skill_view")
    skill_names = [str(a.get("name") or "") for a in skill_views]
    research_skill_loaded = any("research" in n.lower() for n in skill_names)
    checks.append(Check(
        "did not route into the research skill",
        not research_skill_loaded,
        f"skill_view calls: {skill_names or '(none)'}",
    ))

    checks.append(Check(
        "did not submit a research plan",
        not find_calls(invocations, "amp_evaluate_research_plan"),
        f"amp_evaluate_research_plan called {len(find_calls(invocations, 'amp_evaluate_research_plan'))} time(s)",
    ))

    checks.append(Check(
        "did not load configured topics",
        not find_calls(invocations, "amp_load_research_topics"),
        f"amp_load_research_topics called {len(find_calls(invocations, 'amp_load_research_topics'))} time(s)",
    ))

    search_calls = len(find_calls(invocations, "web_search"))
    checks.append(Check("used web_search directly", search_calls > 0, f"{search_calls} web_search call(s)"))

    return checks


def check_no_governance_summary_leak(final_text: str) -> Check:
    present = "Governance summary" in final_text
    return Check(
        "no governance summary leaked into a non-research reply",
        not present,
        "'Governance summary' found in a freshness-routed reply (unexpected)" if present else "not present, as expected",
    )


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------

SCENARIOS = {
    "adhoc": {
        "prompt": "research US market today",
        "check_fn": check_adhoc,
        "expects_research_workflow": True,
    },
    "configured": {
        "prompt": "run my research topics",
        "check_fn": check_configured,
        "expects_research_workflow": True,
    },
    "freshness": {
        "prompt": "what is San Francisco Bay Area weather like today?",
        "check_fn": check_freshness,
        "expects_research_workflow": False,
    },
}


def run_scenario(name: str, api: AmpApi, verbose: bool) -> bool:
    scenario = SCENARIOS[name]
    print(f"\n=== Scenario: {name} ({scenario['prompt']!r}) ===")

    watcher = ApprovalWatcher(api)
    watcher.start()
    try:
        print("  Running hermes chat...")
        session_id, final_text = run_chat(scenario["prompt"])
        print(f"  session_id = {session_id}")
        # Give the approval watcher a moment to catch anything created right
        # at the tail end of the turn (e.g. immediately before the final
        # response is generated).
        time.sleep(APPROVAL_POLL_INTERVAL_SECONDS * 1.5)
    finally:
        watcher.stop()

    ground_truth = inspect_session(session_id)
    checks = list(scenario["check_fn"](ground_truth))
    if scenario["expects_research_workflow"]:
        checks.extend(check_governance_summary(final_text, ground_truth))
        checks.append(check_hitl(watcher.approved))
    else:
        checks.append(check_no_governance_summary_leak(final_text))

    for c in checks:
        print(c.line())

    if verbose:
        print("\n  --- final response ---")
        print("  " + final_text.replace("\n", "\n  "))
        print("  --- tool call sequence ---")
        for n, a in ground_truth["tool_invocations"]:
            print(f"  {n}({json.dumps(a)[:200]})")

    hard_failures = [c for c in checks if not c.passed and c.severity == "fail"]
    ok = not hard_failures
    print(f"  Result: {'PASS' if ok else 'FAIL'} ({len(hard_failures)} hard failure(s))")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", choices=[*SCENARIOS.keys(), "all"])
    parser.add_argument("-v", "--verbose", action="store_true", help="print the full final response and tool trace")
    args = parser.parse_args()

    creds = load_amp_credentials()
    api = AmpApi(creds["AMP_BACKEND_URL"], creds["AMP_API_KEY"])

    names = list(SCENARIOS.keys()) if args.scenario == "all" else [args.scenario]
    results = {name: run_scenario(name, api, args.verbose) for name in names}

    print("\n=== Summary ===")
    for name, ok in results.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
