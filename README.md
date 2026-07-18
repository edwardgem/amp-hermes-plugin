# Hermes AMP Governance Plugin

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

This plugin is a **reference implementation** to show how to quickly add AMP governance to an existing Hermes agent. Two pieces, each installable in one command:

- **The plugin itself** — governs every tool call and (optionally) every LLM call Hermes makes: logging, policy evaluation, HITL approval, blocking.
- **A sample research-agent skill** — a working example of *cost-governed* agent behavior, not just tool allow/block: it proposes a plan with a real projected cost (and token count), gets it approved by AMP, only then spends tokens researching, and reports back with real usage numbers.

If you already run Hermes, you can have both running in a few minutes.

## Quickstart

**1. Prerequisites**
- Hermes installed and running, with a working chat channel (Slack, Telegram, Discord, etc.)
- An AMP account at `https://amp.inquiryon.com` (or your own AMP instance)

**2. Register your Hermes agent in AMP** — one-time, in the AMP UI:
1. Log in to AMP → **Agent Launchpad** → register a new remote agent for Hermes (name/describe it so AMP AI can suggest a relevant policy) → check **Allow auto-start** → **Register**.
2. Create an AMP API key if you don't already have one.
3. On your agent's page, under **Governance** → **Write New Policy** → **eval-policy** → use the AI icon to generate a starter Hermes policy → activate it.

You now have `AMP_API_KEY` and `AMP_AGENT_NAME`. Find `AMP_ORG_ID` and `AMP_USERNAME` under **My Profile**.

**3. Install the plugin** — one command:

```bash
hermes plugins install edwardgem/amp-hermes-plugin --enable
```

**4. Add your AMP credentials** to `~/.hermes/.env`:

```env
AMP_BACKEND_URL=https://amp.inquiryon.com
AMP_USERNAME=your_name@email_domain.com
AMP_API_KEY=amp_k_...
AMP_ORG_ID=O-0011-AB202605010...
AMP_AGENT_NAME=your-hermes-agent-10c8
```

(Optional settings — HITL timeouts, LLM cost enforcement, notifications — are covered in [LLM budget enforcement](#llm-budget-enforcement-phase-2b) below. Defaults are sane; you don't need them to try this out.)

**5. Install the research-agent skills** — one command each. This is the part that demonstrates token/cost governance, not just tool-call governance:

```bash
hermes skills install https://raw.githubusercontent.com/edwardgem/amp-hermes-plugin/main/skills-pointer/amp-research/SKILL.md
hermes skills install https://raw.githubusercontent.com/edwardgem/amp-hermes-plugin/main/skills-pointer/amp-research-topic/SKILL.md
```

Then copy `~/.hermes/plugins/amp-governance/examples/research_topics.yaml` to `~/.hermes/research_topics.yaml` and edit the topics list. This is only needed for "run my configured topics" mode — ad hoc topics named on the spot (e.g. "research the US market") don't need this file at all.

**6. Restart Hermes:**

```bash
hermes gateway restart
```

**7. Try it** — send these through your Hermes channel:
- `Can you run git status in ~/Projects/my-repo?` — a plain governed tool call.
- `Research the US market today.` — the full governed research workflow: a cost-estimated plan, AMP approval, governed research, and a real cost/usage summary in the report.

See "How to verify it is working" below to confirm each piece is genuinely governed, not just running.

## How to verify it is working

Check these places:

- Hermes gateway logs
- Hermes chat surface (Slack, Telegram, Discord, etc.)
- AMP agent log for the Hermes agent
- AMP workitems page if HITL is triggered

You should see AMP entries similar to:

- session started
- user prompt logged
- policy check for a normalized tool/action
- policy decision
- HITL requested, if approval is required

For time-sensitive prompts, you should also see Hermes use `web_search` instead of answering only from model memory.

For HITL prompts in any messaging channel, you should also see messages similar to:

- `[AMP] AMP is waiting for a human reviewer to approve "web_search" before continuing. This action is paused pending review.`
- `[AMP] AMP review approved "web_search". Continuing now.`
- `[AMP] AMP reviewer rejected "web_search". ...`

If LLM observation is enabled, you should also see in AMP logs:

- `LLM call #1 | model=claude-opus-4-8 | tokens=1450 | cost_usd=0.001234 | cost_status=estimated`
- `Execution summary | execution_id=... | llm_calls=4 | total_tokens=5820 | total_cost_usd=0.004932 | cost_status=estimated`

## Common issues

### Plugin loads but does nothing

Check:

- `plugin.yaml` is present in `~/.hermes/plugins/amp-governance`
- `__init__.py` is present in the same directory
- the plugin is enabled:

```bash
hermes plugins enable amp-governance
```

### Hermes starts but AMP governance is not configured

Check that `~/.hermes/.env` contains all required values:

- `AMP_BACKEND_URL`
- `AMP_API_KEY`
- `AMP_ORG_ID`
- `AMP_USERNAME`
- `AMP_AGENT_NAME`

### Tool calls are blocked unexpectedly

Check:

- the active AMP policy for your Hermes agent
- whether the Hermes tool was normalized into a different AMP tool/action than you expected
- whether AMP policy criteria are too broad

### HITL never resolves

Check:

- reviewer assignment in the AMP policy or HITL setup
- `AMP_HITL_TIMEOUT_MINUTES`
- AMP workitems page for pending approvals
- `HERMES_AGENT_TIMEOUT` — if HITL reviews take more than 30 minutes, set this to a higher value (e.g., `HERMES_AGENT_TIMEOUT=7200`)

### Research skill (Phase 3B) stops triggering, or abandons governance mid-run

Symptoms: a message that should trigger the research workflow instead gets a
direct, ungoverned answer; or the workflow starts but `amp_evaluate_research_plan`
fails repeatedly and the model falls back to a raw `web_search`/reports a vague
"internal configuration issue" instead of stopping cleanly.

This is a known failure mode in a **long-running channel/thread**, not a config
problem: the model can anchor on a stale plan shape, topic list, or approval
from earlier in that same conversation instead of following the current skill
instructions, even right after re-loading them. It gets more likely the longer
a thread has been open and the more it has already gone through this workflow.

Fix: start a fresh Hermes session in that channel rather than continuing the
existing thread — a new session has no prior turns to anchor on. In Slack,
send `/new` (or `/hermes new` if `/new` isn't registered as a native Slack
slash command in your workspace — see `hermes slack manifest` in the upstream
Hermes docs to register core commands like `/new` natively). The equivalent
command on other platforms is also `/new`.

### Notifications are not appearing in my channel

Check:

- `AMP_NOTIFICATIONS_ENABLED` is `true` (default)
- Hermes gateway is running with a platform adapter (Slack bot token, Telegram bot token, etc.)
- `HERMES_SESSION_PLATFORM` is set correctly in the gateway for your channel
- The `send_message` tool is enabled and working in your Hermes setup

### LLM observation shows cost_status="unknown"

This is expected for:
- Local models (Ollama, LM Studio, etc.) that are not in Hermes' pricing table
- New models released after the Hermes pricing table was last updated
- Providers where Hermes cannot determine the model name

The session continues normally. Token counts are still recorded; only the cost calculation is unavailable.

### LLM enforcement is configured but not activating

Check:

- `AMP_LLM_GOVERNANCE_ENABLED=true` and `AMP_LLM_GOVERNANCE_MODE=enforce` are set
- The installed Hermes build includes `LLMExecutionBlocked` ([hermes-agent#64662](https://github.com/nousresearch/hermes-agent/issues/64662))
- Hermes gateway logs at startup for the message `"LLM enforcement enabled"`
- If the log shows `"Enforcement middleware was NOT registered"`, you need a Hermes build that includes the upstream change

For local dev, use the `feature/llm-execution-blocking` branch of the Hermes repo.

## What this plugin governs

Hermes tools are normalized into AMP policy vocabulary like this:

- `terminal` → `exec/exec`
- `read_file` → `read/read`
- `search_files` → `read/search`
- `write_file` → `write/write`
- `patch` → `write/edit`
- `web_search` → `exec/web_search`

## Notification bridge

When AMP triggers HITL, the plugin sends a notification back to the originating channel — wherever the user is interacting with Hermes.

**Supported platforms:** Slack, Telegram, Discord, Signal, Matrix, ntfy, and any other platform whose adapter is registered in your Hermes gateway.

**CLI mode:** When Hermes runs in CLI mode (`HERMES_SESSION_PLATFORM=cli` or empty), the notification bridge is a no-op. Governance is still enforced normally; the user sees the outcome through the terminal response text.

**Notification events:**
- Action paused, awaiting human review
- Review approved (or approved with modifications)
- Review rejected
- Review timed out and action blocked

**Failure behavior:** Notification delivery is best-effort. If `send_message` fails for any reason (channel not found, gateway unavailable, network error), the failure is logged at WARNING level and silently swallowed. Governance enforcement never depends on delivery success.

**Configuration:**
```dotenv
# Notifications are on by default. Set to false to disable entirely.
AMP_NOTIFICATIONS_ENABLED=true
```

## Scope: what Phase 2A/2B actually covers

Phase 2A/2B instrument LLM calls made through Hermes' **normal conversational agent loop** — the `pre_api_request`/`post_api_request` hooks and `llm_execution` middleware that fire on every provider call inside `agent/conversation_loop.py`. Every "every LLM call" statement below means every call on *that* path.

They do **not** cover calls a plugin makes via `ctx.llm.complete()` / `ctx.llm.complete_structured()` (the host-owned LLM facade documented at `agent/plugin_llm.py`). That facade calls `agent/auxiliary_client.py::call_llm()` directly and never touches `pre_api_request`, `post_api_request`, or `llm_execution` — verified by inspecting `agent/auxiliary_client.py`, which has no hook-invocation code at all. A plugin LLM call made this way is invisible to AHP's observation and enforcement, full stop.

This is why the Phase 3B research-agent skill (below) deliberately never uses `ctx.llm` for planning or research — every step of that workflow runs as the model's own normal conversational turn specifically so it stays inside AHP's actual coverage.

## LLM usage observation (Phase 2A)

When enabled, the plugin observes every LLM API call made through the normal conversational agent loop (see "Scope" above) and accumulates token usage and estimated cost per session. Observation runs in both `observe` and `enforce` modes.

**What is captured per LLM call:**
- `input_tokens`, `output_tokens`
- `cache_read_tokens`, `cache_write_tokens` (Anthropic prompt caching)
- `reasoning_tokens` (extended thinking)
- `total_tokens`
- Estimated cost in USD (from Hermes' built-in pricing table)
- Cost status: `"estimated"`, `"actual"`, `"included"`, or `"unknown"`
- Wall-clock API duration

**Accumulated per session:**
- All token fields summed across all API calls
- Total estimated cost
- Worst-case cost status (if any call has `"unknown"` cost, the session total is `"unknown"`)
- LLM call count and governed tool call count

**Unknown cost handling:** When a model is not in Hermes' pricing table (local models, custom servers, new models not yet added), cost is recorded as `0.0` with `cost_status="unknown"`. The session continues normally. Do not use observation mode as a budget enforcement mechanism; it records costs that are estimatable and marks the rest as unknown.

**Streaming:** Usage is accumulated after the stream completes. The `post_api_request` hook fires after full completion, so streaming and non-streaming calls are handled identically.

**Retried calls:** Each attempt is counted and accumulated separately. If a call fails and is retried, both the failed attempt (tokens consumed up to failure) and the retry are recorded.

**Concurrent sessions:** Usage data is isolated per `session_id`. Concurrent sessions do not share accumulation state.

**AMP logging:** Each LLM call is logged to AMP with token and cost fields. A final execution summary is logged when the session ends.

## LLM budget enforcement (Phase 2B)

When `AMP_LLM_GOVERNANCE_MODE=enforce`, the plugin evaluates every LLM call against AMP policy **before** the call reaches the model. The policy decision determines whether the call is allowed, requires HITL approval, or is blocked.

**Observe vs enforce:**
- `observe` — accumulates token and cost data, logs to AMP, does not block calls.
- `enforce` — additionally evaluates pre-call policy, pauses for HITL when required, and raises `LLMExecutionBlocked` to cancel blocked calls.

**Hermes capability requirement:**

Enforcement requires `LLMExecutionBlocked` from `hermes_cli.middleware`, which is available in Hermes builds that include the change from [nousresearch/hermes-agent#64662](https://github.com/nousresearch/hermes-agent/issues/64662). The plugin detects the class at import time:

```python
try:
    from hermes_cli.middleware import LLMExecutionBlocked
    _LLM_BLOCKED_AVAILABLE = True
except ImportError:
    _LLM_BLOCKED_AVAILABLE = False
```

If `LLMExecutionBlocked` is not present, the enforcement middleware is **not registered** and an error is logged at startup:

```
amp-governance: AMP_LLM_GOVERNANCE_MODE=enforce is configured but
LLMExecutionBlocked is not available in the installed Hermes
(nousresearch/hermes-agent#64662). Enforcement middleware was NOT
registered. LLM calls will proceed without enforcement.
```

Observation (Phase 2A) continues normally even when enforcement is unavailable.

**Local dev:** Use the `feature/llm-execution-blocking` branch of the Hermes repo, which implements `LLMExecutionBlocked`. Set `AMP_LLM_GOVERNANCE_MODE=enforce` in `~/.hermes/.env`.

**Upstream status:** The `LLMExecutionBlocked` proposal is submitted as [nousresearch/hermes-agent#64662](https://github.com/nousresearch/hermes-agent/issues/64662) and is pending upstream review.

**Policy decisions:**

The pre-call governance signal sent to AMP (`/api/hitl/request`) includes:
- `tool="llm"`, `action="invoke"` for AMP policy matching
- Current session cost (accumulated so far)
- Estimated next-call cost
- Projected total cost after next call
- All token counts for the session

AMP returns one of:
- `no-hitl` / `allow` — call proceeds immediately
- `pending` — HITL required; call is paused
- `no_policy` — no active policy; call is blocked

**HITL flow:**

When AMP requests HITL, the plugin:
1. Notifies the user in their Hermes channel: `"Execution paused pending approval in AMP."` with current/projected cost context
2. Polls AMP for the reviewer's decision (see `AMP_HITL_POLL_INTERVAL_SECONDS`)
3. On approval: resumes the LLM call normally
4. On rejection or timeout: raises `LLMExecutionBlocked` to cancel the call

The reviewer acts in the AMP UI (HITL workitems page). The notification goes to the user's Hermes channel (Slack, Telegram, Discord, etc.), so they know to expect a delay.

**Cost estimation:**

Before the call, the plugin estimates the pending call cost using:
- Input estimate: `max(total_message_chars / 4, 100)` tokens
- Output estimate: 1024 tokens (conservative default)

Estimation uses Hermes' built-in pricing table. For models not in the pricing table (local, custom, new), the estimate is `(0.0, "unknown")`.

**Projected cost limitation:** The projected total cost is `accumulated_cost + estimated_next_call_cost`. It does not include future calls beyond the next one (a plan-level view is not available until Phase 3 plan governance). Use it as a directional signal, not a hard budget bound.

**Fail-open / fail-closed:**

LLM governance defaults to **fail-open**: if AMP is unreachable or returns an unexpected response, the LLM call is allowed to proceed. This is the opposite of tool governance (which defaults fail-closed) because blocking every LLM call on AMP unavailability would halt the agent entirely.

```dotenv
# LLM governance fail behavior. Default: false (fail-open).
AMP_LLM_GOVERNANCE_FAIL_CLOSED=false
```

This setting applies only to AMP unavailability and unexpected AMP responses. Explicit block decisions (`no_policy`, reviewer rejection, HITL timeout) always block regardless of this setting.

**Configuration:**

```dotenv
# Off by default. Set to true to enable LLM observation and enforcement.
AMP_LLM_GOVERNANCE_ENABLED=false

# Mode: "observe" (accumulate only) or "enforce" (pre-call policy eval + block).
# "enforce" requires Hermes with LLMExecutionBlocked (hermes-agent#64662).
AMP_LLM_GOVERNANCE_MODE=observe

# LLM governance fail behavior. Default: false (fail-open).
# When true, LLM calls are blocked if AMP is unreachable.
AMP_LLM_GOVERNANCE_FAIL_CLOSED=false

# Whether to track LLM calls from subagents launched by this session.
AMP_LLM_GOVERNANCE_INCLUDE_SUBAGENTS=true
```

## Plan approval (Phase 3A)

Phase 2B enforces a budget on every LLM call — but it doesn't have a budget until something sets one. Phase 3A is that missing piece: a **plan-governance interface** a caller uses once, up front, to get a proposed execution plan approved by AMP and turn that approval into the runtime budget Phase 2B enforces for the rest of the session.

This is AHP-only plumbing. It does **not** decide what a "plan" is, read any config file, call a planning LLM, or react to a chat trigger — composing the plan and deciding when to submit it is entirely the caller's job (a future research-agent skill, or any other Hermes-side workflow). AHP's job is only: take a plan dict, get it approved, wire up the budget.

**Interface:**

```python
result = evaluate_proposed_plan(
    session_id,
    plan={
        "plan_type": "research",
        "summary": "Research five configured topics",
        "projected_cost_usd": 4.75,
        "projected_cost_status": "estimated",  # optional, default "estimated"
        "estimated_llm_calls": 18,              # optional, default 0
        "estimated_tool_calls": 25,              # optional, default 0
        "estimated_duration_minutes": 20,        # optional, default 0
        "work_units_total": 5,                   # optional, default 0
        "payload": {"topics": [...]},            # optional, opaque to AHP
    },
)
```

`evaluate_proposed_plan` is exported at module level (`from hermes import evaluate_proposed_plan` in this dev tree; once installed as a Hermes plugin, `amp_governance.evaluate_proposed_plan(...)`). It delegates to `AmpGovernancePlugin.evaluate_proposed_plan`.

**Validation:** only the two governance-relevant fields are required — `plan_type` (non-empty string) and `projected_cost_usd` (non-negative number). A missing/invalid required field returns an error result immediately, without contacting AMP. Everything else is optional with safe defaults. `payload` is never interpreted by AHP — it is included in the AMP request's `context` unmodified and is meant for the caller's own downstream use (e.g. a Phase 3B execution step).

**AMP normalization:** the plan is submitted through the existing `/api/hitl/request` path (same endpoint tool/LLM governance already use) — no new AMP API, no AMP schema change:

```json
{
  "tool": "execution_plan",
  "action": "submit",
  "plan_id": "...",
  "plan_type": "research",
  "plan_projected_cost_usd": 4.75,
  "plan_projected_cost_status": "estimated",
  "plan_estimated_llm_calls": 18,
  "plan_estimated_tool_calls": 25,
  "plan_estimated_duration_minutes": 20,
  "plan_work_units_total": 5
}
```

These flat fields are promoted to policy `params` automatically, so an AMP eval-policy criterion can reference them directly, e.g. auto-approve when `plan_projected_cost_usd < 5.0`, otherwise require HITL.

**Decision outcomes:**

| AMP response | Result `status` | `approved_budget_usd` |
|---|---|---|
| `no-hitl` / `allow` / `allowed` / `approved` | `approved` | set immediately |
| `pending` + HITL approve/modify | `approved` | set after reviewer decision |
| `pending` + HITL reject | `rejected` | not set |
| `pending` + HITL timeout | `timed_out` | not set |
| `no_policy` | `rejected` | not set |
| AMP unreachable, or unexpected status | `error` | not set |

The full result shape:

```python
{"status": "approved", "plan_id": "...", "approved_budget_usd": 4.75, "reason": "", "workitem_id": None}
```

**Approved-budget initialization:** on approval (auto or HITL), AHP sets `approved_budget_usd` on the session's `ExecutionContext` to the plan's own `projected_cost_usd` — never a recomputed value. The `ExecutionContext` is created if `on_session_start` hadn't already created one, since Phase 2B's `llm_execution_middleware` silently allows calls when no context is tracked; without this, an approved plan would never actually constrain anything. From that point on, every LLM call in the session is evaluated against this budget by the existing Phase 2B enforcement path — no additional wiring needed.

Phase 3B (below) builds on this interface with a working sample: a skill that detects the chat trigger, loads a topics config file, builds the plan, and calls `amp_evaluate_research_plan`.

## Research sample (Phase 3B)

An end-to-end demo of everything above: a user sends a chat message, a skill loads their configured topics (or a specific topic they named on the spot), proposes a plan, waits for AMP approval, researches only after approval, and reports back — with every LLM call along the way governed by Phase 2A/2B (see "Scope" above: this only works because the whole workflow runs as the model's own normal conversational turns, never via `ctx.llm`). Install steps are in the top-level Quickstart; this section covers how it works.

Two ways to trigger it:
- **Configured mode**: `Run my research topics.` — researches whatever's in your `research_topics.yaml`.
- **Ad hoc mode**: `Research the US market.` (or any specific topic) — researches just that topic, using sensible defaults (`research_depth: standard`, `sources_per_topic: 5`, `lookback_days: 30`) since there's no config entry for a one-off request. Same plan-approval → research → report pipeline either way; only the topic source differs.

**Three registered tools** (`ctx.register_tool()`, wired in `register()`, not listed under `plugin.yaml`'s `hooks:` since tools are a separate registration API):
- `amp_evaluate_research_plan({"plan": {...}})` — thin wrapper around `evaluate_proposed_plan()` above. Sources `session_id` from `gateway.session_context.get_session_env("HERMES_SESSION_ID", "")` (the same pattern the notification bridge already uses for platform/chat/thread) rather than trusting the model to supply one. Used identically by both configured and ad hoc mode — AHP has no concept of "mode," it only ever sees a plan dict.
- `amp_load_research_topics({"path": "..."})` — validates `~/.hermes/research_topics.yaml` (or an override path) via `research_config.load_research_topics()`: 1-5 topics required, defaults applied for `research_depth`/`sources_per_topic`/`lookback_days`. Exists so config loading is deterministic Python, not the model hand-parsing YAML. Called only in configured mode — ad hoc mode skips it entirely (see the skill's step 0).
- `amp_governance_summary()` — returns the session's current `ExecutionContext.to_summary_dict()` (cost, tokens, call counts) so the skill's final report uses real numbers instead of inventing them. Returns `{"status": "no_context"}` if nothing has been tracked yet.

**Three skills:**
- `skills/research-agent/SKILL.md` — plugin-bundled (`ctx.register_skill()`), the actual step-by-step workflow, shared by both modes. Step 0 determines which mode a given trigger is (configured vs ad hoc) and branches accordingly; everything from plan-building onward (steps 2-8) is identical regardless of mode. Plugin-bundled skills are **not** auto-listed in the system prompt's skill index (they're opt-in explicit loads only), so this alone isn't discoverable by natural language.
- `skills-pointer/amp-research/SKILL.md` — configured-mode entry point, matches phrasing like "Run my research topics."
- `skills-pointer/amp-research-topic/SKILL.md` — ad hoc-mode entry point, matches phrasing like "Research the US market." Deliberately a **separate** pointer skill rather than one pointer covering both cases — two narrowly-scoped skill descriptions give the LLM-mediated routing a much cleaner signal than one description trying to cover two different intents, which is exactly the kind of ambiguity that produced flaky routing in earlier testing. In practice, AHP's own `pre_llm_call` hook now routes straight to the real skill and decides the mode itself whenever a message mentions "research," so these pointer skills mainly matter as the natural-language-discoverable entry point when that hook isn't the one driving (e.g. a direct `skill_view` call).

Neither pointer skill is plugin-bundled (both must be installed to `~/.hermes/skills/`, see Quickstart), so both *are* auto-indexed and matched by natural language. Their entire body is: call `skill_view(name="amp-governance:research-agent")` and follow it. There is deliberately no separate `ctx.register_command()` for either — a plugin-registered command's return value is sent directly as the reply and cannot hand off to the model's multi-turn loop (verified against `gateway/run.py`), so it couldn't have driven this workflow anyway. Natural language alone is the supported entry point; Hermes' per-skill slash-command derivation (`agent/skill_commands.py`) technically also gives each of these a `/amp-research` / `/amp-research-topic` command, but on Slack specifically that name is intercepted by Slack's own reserved `/` namespace before it ever reaches Hermes (confirmed live — Slack rejects it client-side unless separately registered as a native Slack Slash Command, out of scope here), so it isn't a reliable cross-platform entry point and isn't documented as one.

**Pointer skill installation:** previously a manual copy/symlink step into `~/.hermes/skills/research/`. Now a one-liner per skill via `hermes skills install <URL-to-SKILL.md>` (see Quickstart) — Hermes' own skill installer accepts a direct HTTPS URL to a `SKILL.md` file, which resolves this cleanly for a human running setup. A plugin still cannot auto-place a *non-bundled, auto-indexed* skill into the user-local skill tree on the user's behalf with zero commands at install time (plugin-bundled skills are deliberately excluded from that index — see Phase 3A `evaluate_proposed_plan`'s doc above); that narrower gap remains open if it matters to you.

**Testing this workflow end-to-end:** `scripts/e2e_research_test.py adhoc|configured|freshness|all` drives a real `hermes chat` turn for each mode, auto-approves any AMP plan-approval workitem via the same API AHP itself uses (`X-API-Key` from `~/.hermes/.env`, no browser/Slack needed), and cross-checks the result against `~/.hermes/state.db` — catches wrong-skill routing, a missing/invented plan cost, a governance summary that doesn't match what actually happened, and (via the `freshness` scenario) a plain time-sensitive question getting wrongly diverted into the governed workflow instead of a direct `web_search`. Makes real LLM calls (small real cost per run); not part of `pytest tests/`. Run with the hermes-agent venv (`.../hermes-agent/venv/bin/python`, for `pyyaml`).

**Not implemented this cycle:** cron scheduling (see `hermes cron create ... --skills "amp-governance:research-agent"` in `HERMES_RESEARCH_SAMPLE_INTEGRATION_ASSESSMENT.md` §5 for the verified path once someone wants it), topic-management UI, plan revision loops, multiple report formats, ad hoc topics longer than 5 (silently capped, see the skill's step 0), a `plan_type` distinction between the two modes (both submit `plan_type: "research"` — deliberately kept as a skill-instruction-only distinction, not a governance-signal one, for this cycle).

## Files in this plugin

- `plugin.yaml` — Hermes plugin manifest
- `__init__.py` — main plugin hooks and governance flow
- `amp_client.py` — AMP API client
- `config.py` — config loading from `~/.hermes/.env`
- `execution_context.py` — per-session LLM usage accumulation
- `notification.py` — platform-neutral notification bridge
- `policy.py` — Hermes tool normalization into AMP policy vocabulary
- `session_store.py` — session-to-AMP instance tracking
- `research_config.py` — research_topics.yaml loading/validation (Phase 3B)
- `skills/research-agent/SKILL.md` — plugin-bundled research workflow (Phase 3B)
- `skills-pointer/amp-research/SKILL.md`, `skills-pointer/amp-research-topic/SKILL.md` — small discoverable pointer skills (configured mode, ad hoc mode); install via `hermes skills install <URL>` (Phase 3B, see Quickstart)
- `examples/research_topics.yaml` — template config read by the research-agent skill at runtime (the planning-prompt schema is inlined in the skill itself)
- `scripts/e2e_research_test.py` — end-to-end test harness for the research workflow (see Phase 3B above)
- `.env.example` — example environment variables for setup
- `LICENSE` — MIT open-source license

## Development note

For local development, symlink install is easier than `hermes plugins install` because Hermes will load the plugin directly from your working repo, and edits take effect on the next gateway restart with no reinstall step:

```bash
mkdir -p ~/.hermes/plugins
ln -s /path/to/amp-hermes-plugin ~/.hermes/plugins/amp-governance
hermes plugins enable amp-governance
hermes gateway restart
```
