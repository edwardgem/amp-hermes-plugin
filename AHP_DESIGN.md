# AMP-Hermes Plugin: Resource Governance Architecture Assessment

**Date:** 2026-07-14  
**Hermes version:** v0.16.0 (2026.6.5)  
**AHP version:** 0.1.0  
**Scope:** Phases 1–3 design; no implementation started  
**Status:** Awaiting product-owner review

---

## 1. Executive Summary

The AMP-Hermes Plugin (AHP) currently governs tool calls: it intercepts pre-tool-call events, evaluates them against AMP policy, enforces HITL approval, and blocks disallowed actions. The plugin is small (six files) and well-isolated from Hermes internals.

The three proposed extensions are:

| Phase | Name | Hermes core change required? |
|---|---|---|
| 1 | Notification bridge | **No** — AHP-only change |
| 2 | Runtime LLM resource governance | **Small targeted change needed** for Phase 2B blocking only |
| 3A | Generic proposed-plan governance | No |
| 3B | Research-agent sample | No (agent code, not plugin) |

**Key findings:**

- Hermes already provides `pre_api_request` and `post_api_request` hooks with full canonical token usage data. These are the natural extension points for Phase 2A observation.
- Hermes already normalizes token usage across all providers (Anthropic, OpenAI, Gemini, Bedrock, Ollama, OpenRouter) into a `CanonicalUsage` dataclass and calculates cost via `estimate_usage_cost()` in `agent/usage_pricing.py`.
- Hermes already provides `get_session_env()` in `gateway/session_context.py` with task-local context variables for platform, chat_id, thread_id, user_id, and session_id. AHP already calls this for Slack only; the fix to generalize the notification bridge to all platforms is AHP-only.
- The agent execution loop runs in a thread executor. Synchronous blocking inside plugin hooks (current HITL mechanism) does not freeze the async event loop, and the gateway is protected by a configurable inactivity timeout (default 30 min).
- For Phase 2B (blocking before an LLM call), the current `llm_execution` middleware exception-handling design falls through on any `Exception`, meaning middleware cannot block the LLM call by raising. A small targeted Hermes change is needed to support a governance-block signal.
- AMP's existing `/api/hitl/request` endpoint already accepts arbitrary flat fields as policy signals. No AMP schema changes are needed for Phases 1 or 2. Cost and token signals can be added as top-level payload fields that become policy `params` automatically.

---

## 2. Current AHP Architecture

### 2.1 Where AHP Lives

AHP is a user plugin installed at `~/.hermes/plugins/amp-governance/`. It consists of six files:

| File | Purpose |
|---|---|
| `plugin.yaml` | Hermes plugin manifest (name, version, hooks list) |
| `__init__.py` | Main plugin: `AmpGovernancePlugin` class and `register(ctx)` function |
| `amp_client.py` | HTTP client for AMP backend API |
| `config.py` | Config loading from `~/.hermes/.env` |
| `policy.py` | Hermes-to-AMP tool normalization |
| `session_store.py` | Persistent session-to-instance-id mapping |

### 2.2 How Hermes Loads AHP

Hermes discovers plugins via `hermes_cli/plugins.py:PluginManager.discover_and_load()`. The flow is:

1. `hermes plugins enable amp-governance` adds `amp-governance` to `plugins.enabled` in `~/.hermes/config.yaml`.
2. On gateway startup, `discover_plugins()` scans `~/.hermes/plugins/`, finds `amp-governance/plugin.yaml`, loads `__init__.py`, and calls `register(ctx)`.
3. `register(ctx)` registers six hooks on the `PluginContext` object.

The `ctx` object is an instance of `hermes_cli/plugins.py:PluginContext`. It provides `ctx.register_hook(name, fn)` and `ctx.dispatch_tool(name, args)`.

### 2.3 Hooks Currently Used by AHP

Registered in `hermes/__init__.py:register()`:

| Hook | What AHP does |
|---|---|
| `on_session_start` | Calls `AmpClient.init_instance()` to create/retrieve an AMP agent instance for the session |
| `on_session_finalize` | Calls `AmpClient.set_state("finished")` and removes session from `SessionStore` |
| `pre_llm_call` | Logs the user prompt; injects date/web-search context for time-sensitive queries |
| `pre_tool_call` | Normalizes the tool call; evaluates against AMP policy via `request_hitl`; blocks or HITL-pauses |
| `post_tool_call` | Logs tool result to AMP |
| `transform_llm_output` | Replaces the final response text with a generic block message when a tool was blocked this turn |

**Not currently used by AHP but available:**

| Hook | Relevance to extension |
|---|---|
| `post_llm_call` | Per-turn post-LLM observer (limited data) |
| `pre_api_request` | Per-API-call pre-LLM observer (approx token count, model, provider) |
| `post_api_request` | Per-API-call post-LLM observer with **full canonical usage** |
| `api_request_error` | Error observer per failed API call |
| `subagent_start` / `subagent_stop` | Subagent lifecycle hooks |
| `on_session_end` / `on_session_reset` | Session lifecycle hooks |

### 2.4 How Tool-Call Governance Works (Current End to End)

```
User message → Hermes agent loop
  → LLM returns tool_calls
  → agent/tool_executor.py calls get_pre_tool_call_block_message()
     → hermes_cli/plugins.py:invoke_hook("pre_tool_call", tool_name=..., args=..., session_id=...)
        → AmpGovernancePlugin.pre_tool_call()
           → policy.normalize_tool_call(tool_name, args)   # Hermes→AMP vocabulary
           → _ensure_instance(session_id)                   # init AMP instance if needed
           → _evaluate_governance(instance_id, action)
              → AmpClient.request_hitl(instance_id, action)
              → if status == "no-hitl" → return None       # allow
              → if status == "no_policy" → block
              → if status == "pending"/"waiting-for-response":
                 → _notify_slack("waiting…")
                 → while time.time() < deadline:
                    → time.sleep(poll_interval)             # SYNCHRONOUS BLOCK in thread
                    → AmpClient.get_hitl_decision()
                    → if complete + approved → return None  # allow
                    → if complete + rejected → return block
                 → timeout → return block
  → if block message returned → tool is skipped
  → transform_llm_output replaces response text with block message
```

**File citations:**
- `hermes/__init__.py:290–323` — `pre_tool_call`
- `hermes/__init__.py:159–244` — `_evaluate_governance`
- `hermes/__init__.py:143–157` — `_notify_slack`
- `hermes/amp_client.py:95–119` — `request_hitl`, `get_hitl_decision`

### 2.5 Current Identity, Session, and Config

**User/agent identity:** Read from `~/.hermes/.env` at startup: `AMP_ORG_ID`, `AMP_AGENT_NAME`, `AMP_USERNAME`.  
**Session identification:** The `session_id` kwarg passed by Hermes to each hook.  
**AMP instance:** Created once per `session_id` via `POST /api/agent/init`; stored in `SessionStore` (JSON file at `~/.hermes/plugin_state/amp-governance/sessions.json`).  
**Policy evaluation:** `POST /api/hitl/request` — acts as combined policy-evaluation + HITL gateway.  
**HITL polling:** `GET /api/hitl/get-decision?caller_id=<instance_id>` — synchronous polling loop.  
**Fail mode:** `AMP_FAIL_CLOSED=true` (default) → block on AMP unavailability.

### 2.6 Backward Compatibility Contract

The following must remain unchanged:
- Hook registrations: `on_session_start`, `on_session_finalize`, `pre_llm_call`, `pre_tool_call`, `post_tool_call`, `transform_llm_output`
- `AmpConfig` field names and env-var names
- `SessionStore` file format (or a migration path)
- `NormalizedAction` dataclass
- `normalize_tool_call()` return values
- All `AmpClient` method signatures
- The `plugin.yaml` manifest name (`amp-governance`)
- The block return format `{"action": "block", "message": "..."}`

---

## 3. Verified Hermes Extension Points

All findings below are verified from source code. File and line numbers are cited.

### 3.1 Plugin Hook System

**File:** `hermes_cli/plugins.py:128–170`

```python
VALID_HOOKS = {
    "pre_tool_call",            # Can block: {"action": "block", "message": "..."}
    "post_tool_call",           # Observer
    "transform_terminal_output",# Observer (can modify terminal output string)
    "transform_tool_result",    # Observer
    "transform_llm_output",     # Can replace response text (first non-None wins)
    "pre_llm_call",             # Can inject context: {"context": "..."}
    "post_llm_call",            # Observer per turn
    "pre_api_request",          # Observer per API call — VERIFIED, see §3.3
    "post_api_request",         # Observer per API call with usage — VERIFIED, see §3.4
    "api_request_error",        # Observer per failed call
    "on_session_start",
    "on_session_end",
    "on_session_finalize",
    "on_session_reset",
    "subagent_start",
    "subagent_stop",
    "pre_gateway_dispatch",     # Can skip/rewrite/allow incoming messages
    "pre_approval_request",     # Observer
    "post_approval_response",   # Observer
}
```

Hook invocation is **synchronous**: `hermes_cli/plugins.py:invoke_hook()` calls `cb(**kwargs)` without `await`. Async handlers can be registered but their coroutines are not awaited by the plugin hook system. Plugins must be synchronous or manage their own threading.

### 3.2 Middleware System

**File:** `hermes_cli/middleware.py:29–34`

In addition to hooks, Hermes supports four middleware types:

| Middleware kind | What it wraps |
|---|---|
| `tool_request` | Tool argument rewriting before hooks/guardrails |
| `tool_execution` | Wraps the actual tool execution with `next_call` |
| `llm_request` | LLM request rewriting before API call |
| `llm_execution` | Wraps the actual LLM API call with `next_call` |

Middleware is registered via `ctx.register_middleware(kind, callback)`. The `llm_execution` middleware callback receives `(request, next_call, session_id, model, provider, ...)` and can act before AND after calling `next_call(request)`.

**Critical limitation for Phase 2B blocking:** When `llm_execution` middleware raises an `Exception` without calling `next_call`, the exception handler at `hermes_cli/middleware.py:287–300` catches it and falls through to the next middleware (or the terminal provider call). Middleware **cannot block the LLM call by raising an `Exception`**. See §7 (Gaps) for the proposed Hermes change.

### 3.3 `pre_api_request` Hook Arguments

**File:** `agent/conversation_loop.py:903–953`

Fires once per LLM API call, before the provider request:

```python
invoke_hook(
    "pre_api_request",
    task_id=...,
    turn_id=...,
    api_request_id=...,
    session_id=...,
    user_message=...,
    conversation_history=[...],
    platform=...,
    model=...,
    provider=...,
    base_url=...,
    api_mode=...,
    api_call_count=...,          # 1-based counter for this turn
    request_messages=[...],
    message_count=...,
    tool_count=...,
    approx_input_tokens=...,     # rough estimate only
    request_char_count=...,
    max_tokens=...,
    started_at=...,
    middleware_trace=[...],
    request={...},               # sanitized provider kwargs
)
```

Return values are **ignored**. This hook is observer-only.

### 3.4 `post_api_request` Hook Arguments

**File:** `agent/conversation_loop.py:3343–3378`

Fires once per LLM API call, after the provider response is received and normalized:

```python
invoke_hook(
    "post_api_request",
    task_id=...,
    turn_id=...,
    api_request_id=...,
    session_id=...,
    platform=...,
    model=...,
    provider=...,
    base_url=...,
    api_mode=...,
    api_call_count=...,
    api_duration=...,            # wall-clock seconds
    started_at=...,
    ended_at=...,
    finish_reason=...,           # "stop" | "tool_calls" | "length" | ...
    message_count=...,
    response_model=...,          # model reported by provider
    response={...},              # sanitized response dict
    usage={                      # CanonicalUsage fields as dict
        "input_tokens": ...,
        "output_tokens": ...,
        "cache_read_tokens": ...,
        "cache_write_tokens": ...,
        "reasoning_tokens": ...,
        "prompt_tokens": ...,    # input + cache_read + cache_write
        "total_tokens": ...,
    },
    assistant_message=...,       # assistant message object
    assistant_content_chars=...,
    assistant_tool_call_count=...,
)
```

Return values are **ignored**. This hook is observer-only. The `usage` dict is produced by `run_agent.py:_usage_summary_for_api_request_hook()`, which calls `agent/usage_pricing.py:normalize_usage()`.

### 3.5 `llm_execution` Middleware Invocation

**File:** `agent/conversation_loop.py:1008–1025`

```python
from hermes_cli.middleware import run_llm_execution_middleware

response = run_llm_execution_middleware(
    api_kwargs,
    _perform_api_call,               # terminal: actually calls the provider
    original_request=_original_api_kwargs,
    task_id=..., turn_id=..., api_request_id=...,
    session_id=..., platform=..., model=...,
    provider=..., base_url=..., api_mode=...,
    api_call_count=..., middleware_trace=...,
)
```

Middleware callbacks receive `(request, next_call, session_id, model, provider, ...)` and must call `next_call(request)` to proceed. Fires on every LLM call, including retries and tool loops.

### 3.6 Token and Cost Infrastructure

**File:** `agent/usage_pricing.py`

```python
# CanonicalUsage dataclass (line 31)
@dataclass(frozen=True)
class CanonicalUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    raw_usage: Optional[dict] = None

    @property
    def prompt_tokens(self) -> int:    # input + cache_read + cache_write
    @property
    def total_tokens(self) -> int:     # prompt_tokens + output_tokens

# Cost calculation (line 776)
def estimate_usage_cost(
    model_name: str,
    usage: CanonicalUsage,
    *,
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> CostResult:
    ...

# CostResult (line 71)
@dataclass(frozen=True)
class CostResult:
    amount_usd: Optional[Decimal]
    status: CostStatus          # "actual" | "estimated" | "included" | "unknown"
    source: CostSource          # "provider_cost_api" | "official_docs_snapshot" | ...
    label: str
    notes: tuple[str, ...]
```

Hermes ships a static pricing table in `usage_pricing.py` covering dozens of models across all major providers.

### 3.7 Session Context Variables

**File:** `gateway/session_context.py:51–83`

All of the following are set per-message-task before the agent loop runs:

| Variable | Content |
|---|---|
| `HERMES_SESSION_PLATFORM` | `"telegram"`, `"slack"`, `"discord"`, `"signal"`, `"matrix"`, `"cli"`, etc. |
| `HERMES_SESSION_CHAT_ID` | Platform-native chat identifier |
| `HERMES_SESSION_CHAT_NAME` | Human-readable channel/chat name |
| `HERMES_SESSION_THREAD_ID` | Telegram topic ID, Discord thread ID, or empty |
| `HERMES_SESSION_USER_ID` | Platform user identifier |
| `HERMES_SESSION_USER_NAME` | Platform username |
| `HERMES_SESSION_KEY` | Hermes internal session key |
| `HERMES_SESSION_ID` | Hermes session UUID |
| `HERMES_SESSION_MESSAGE_ID` | Originating message ID (reply anchor) |

Readable from plugin code via:
```python
from gateway.session_context import get_session_env
platform = get_session_env("HERMES_SESSION_PLATFORM", "")
```

Values are stored in `contextvars.ContextVar` (task-local, concurrency-safe) with `os.environ` fallback for CLI and cron contexts.

### 3.8 `send_message` Tool

**File:** `tools/send_message_tool.py:127–163`

Hermes ships a built-in cross-platform outbound message tool. Target format:

| Target string | Routes to |
|---|---|
| `"slack:C1234:1712.100"` | Slack channel C1234, thread 1712.100 |
| `"telegram:-1001234:17585"` | Telegram group, topic 17585 |
| `"discord:999888:555444"` | Discord server channel, thread |
| `"signal:+155554567"` | Signal number |
| `"matrix:!room:server.org"` | Matrix room |
| `"ntfy:alerts-channel"` | ntfy topic |
| `"origin"` | Back to originating conversation |

AHP currently calls this tool via `ctx.dispatch_tool("send_message", {"target": target, "message": msg})` in `hermes/__init__.py:150–157`. The current target is built only for Slack (`_build_slack_target()`). Generalization to all platforms requires no Hermes change.

### 3.9 Agent Execution Threading Model

**File:** `gateway/run.py:14971–14972`

The gateway dispatches each message to an executor thread:
```python
_executor_task = asyncio.ensure_future(
    self._run_in_executor_with_context(run_sync)
)
```

The agent loop (including all plugin hook callbacks) runs in the **executor thread pool**, not in the asyncio event loop. This means `time.sleep()` in a hook callback blocks only the executor thread — the asyncio event loop remains free to handle other messages. This is why the current HITL pause mechanism (sleeping inside `pre_tool_call`) works without freezing the gateway.

**Inactivity timeout:** `gateway/run.py:14966` — `HERMES_AGENT_TIMEOUT` env var, default 1800s (30 minutes). A paused execution that has no hook activity for 30 minutes will be killed by the gateway.

### 3.10 Subagent Hooks

**File:** `hermes_cli/plugins.py:144–145`

`subagent_start` and `subagent_stop` hooks fire when a delegated subagent begins or ends. The `subagent_stop` kwargs include `parent_session_id`, `child_role`, `child_status`, `duration_ms`, and `child_summary`. Token usage from subagents is not directly passed in these hooks today; it would need to come from the `post_api_request` hooks fired within the subagent's own execution context.

---

## 4. Verified Gaps

| Gap | Impact | Hermes change needed? |
|---|---|---|
| `pre_api_request` hook return value is ignored | Cannot block LLM calls via this hook | Yes, for blocking only |
| `llm_execution` middleware falls through on exception | Cannot block LLM calls by raising Exception | Yes — targeted change |
| `post_api_request` usage dict has no cost calculation | AHP must call `estimate_usage_cost()` itself | No — callable from AHP |
| Notification bridge is Slack-only | Other channels receive no governance notifications | No — AHP-only fix |
| `plugin.yaml` does not declare `post_api_request` hook | Informational only; hooks work regardless | No |
| `SessionStore` tracks only `session_id → instance_id` | No execution-scoped cost/token accumulator | No — add in AHP |
| AMP `/api/hitl/request` has no budget signal schema | Budget signals must be passed as flat fields | No — existing mechanism works |
| No `execution_id` concept in current AHP | Cannot correlate plan evaluation with runtime events | No — AHP generates its own |
| HITL poll kills inactivity timer | Long HITL waits may trigger gateway timeout | No — set HERMES_AGENT_TIMEOUT |
| Subagent `post_api_request` fires in child context | Parent AHP instance does not see child usage directly | No — child hooks still fire |

---

## 5. Notification Bridge Design Options

### Option A — Generalize Existing `dispatch_tool("send_message")` (Recommended)

AHP already routes Slack notifications by calling `dispatch_tool("send_message", {"target": "slack:...", "message": "..."})`. The `send_message` tool already supports all platforms.

The only change needed: replace `_build_slack_target()` with `_build_notification_target()` that reads `HERMES_SESSION_PLATFORM`, `HERMES_SESSION_CHAT_ID`, and `HERMES_SESSION_THREAD_ID` from `get_session_env()` and constructs the appropriate platform-native target string.

```python
def _build_notification_target(self) -> str:
    try:
        from gateway.session_context import get_session_env
    except Exception:
        return ""
    platform = get_session_env("HERMES_SESSION_PLATFORM", "").strip().lower()
    if not platform or platform == "cli":
        return ""
    chat_id = get_session_env("HERMES_SESSION_CHAT_ID", "").strip()
    if not chat_id:
        return ""
    thread_id = get_session_env("HERMES_SESSION_THREAD_ID", "").strip()
    return f"{platform}:{chat_id}:{thread_id}" if thread_id else f"{platform}:{chat_id}"
```

**Pros:** No Hermes change. Uses proven path. Works for all supported platforms.  
**Cons:** Only works when a gateway adapter is running (not CLI).

### Option B — Use Gateway Delivery Router Directly

Call `gateway/delivery.py:DeliveryRouter.deliver()` directly, bypassing the tool dispatch path.

**Pros:** More control over delivery metadata.  
**Cons:** Couples AHP to an internal Hermes class. Not part of the public plugin API.

### Option C — Ask Hermes to Add a Plugin Notification API

Request a `ctx.notify_user(message, event_type, metadata)` method on `PluginContext`.

**Pros:** Clean public API.  
**Cons:** Requires Hermes core change. Slower to ship.

---

## 6. Recommended Notification Bridge Design

**Recommendation: Option A** — generalize `_build_slack_target()` to `_build_notification_target()`.

**No Hermes change required.**

### Proposed Plugin API (AHP-internal)

```python
def _notify_user(self, message: str, *, event_type: str = "", metadata: dict | None = None) -> None:
    """Send a best-effort status notification to the originating channel."""
    if not callable(self._dispatch_tool):
        return
    target = self._build_notification_target()
    if not target:
        return
    try:
        raw = self._dispatch_tool(
            "send_message",
            {"target": target, "message": f"[AMP]\n{message}"}
        )
        if not raw:
            return
        payload = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(payload, dict) and payload.get("error"):
            logger.warning("amp-governance notify failed: %s", payload["error"])
    except Exception as exc:
        logger.warning("amp-governance notify failed: %s", exc)
```

**Guarantees:**
- Delivery failure does not propagate (exception is caught and logged).
- Governance enforcement never depends on delivery success.
- Notifications are best-effort — they do not gate resume or rejection.

**CLI behavior:** `HERMES_SESSION_PLATFORM` is `""` or `"cli"` in CLI sessions. `_build_notification_target()` returns `""`, so `_notify_user()` is a no-op. The CLI user observes governance through the turn response text.

---

## 7. Pre-LLM and Post-LLM Interception Options

### Option A — Observer Hooks Only (`pre_api_request` + `post_api_request`)

Use existing hooks. `post_api_request` fires after every provider call with canonical usage. AHP accumulates usage and cost internally. Cannot block.

**Suitable for:** Phase 2A (observation) only.

### Option B — `llm_execution` Middleware for Wrapping

Register `llm_execution` middleware. Callback receives `(request, next_call, ...)`. Can:
- Inspect the request before calling `next_call`
- Intercept the response after `next_call` returns
- Sleep in the thread (pause) without freezing the event loop
- Update accumulator before and after

**Cannot block by raising `Exception`** — the middleware exception handler catches it and falls through to the terminal provider call.

**Suitable for:** Phase 2A and Phase 2B (with Hermes change described below).

### Option C — Small Hermes Middleware Change (Required for Phase 2B Blocking)

Add a sentinel exception class to `hermes_cli/middleware.py` that is **not** a subclass of `Exception` (i.e., inherits from `BaseException` directly). The middleware `_run_execution_chain` function catches only `Exception`, so this sentinel would propagate naturally.

Proposed addition to `hermes_cli/middleware.py`:

```python
class GovernanceBlock(BaseException):
    """Raised by governance middleware to unconditionally block an LLM call.

    Unlike Exception subclasses, this propagates through the middleware
    exception-handler fall-through path and is intended to be caught by
    callers that understand governance semantics.
    """
    def __init__(self, reason: str, *, event_type: str = "blocked") -> None:
        super().__init__(reason)
        self.reason = reason
        self.event_type = event_type
```

The conversation loop (`agent/conversation_loop.py`, around line 1010) would add:

```python
try:
    response = run_llm_execution_middleware(
        api_kwargs, _perform_api_call, ...
    )
except GovernanceBlock as exc:
    # Return synthetic blocked response to the conversation loop
    # so the agent can tell the user the action was blocked.
    logger.info("LLM call blocked by governance: %s", exc.reason)
    return {
        "final_response": f"This request was blocked by governance: {exc.reason}",
        "messages": messages,
        "api_calls": api_call_count,
        "completed": True,
        "blocked": True,
    }
```

This is a **12-line Hermes change** confined to two files: `hermes_cli/middleware.py` and `agent/conversation_loop.py`.

---

## 8. Recommended Interception Design

### Phase 2A — Observation (No Hermes Change)

Register `post_api_request` hook in `register(ctx)`. The hook receives normalized usage per API call. AHP maintains an `ExecutionContext` (in memory, keyed by `session_id`) that accumulates totals.

```python
ctx.register_hook("post_api_request", _PLUGIN.post_api_request_hook)
```

The hook callback:
```python
def post_api_request_hook(
    self,
    session_id: str = "",
    model: str = "",
    provider: str = "",
    base_url: str = "",
    api_call_count: int = 0,
    usage: dict | None = None,
    api_duration: float = 0.0,
    **_,
) -> None:
    ctx = self._exec_context.get(session_id)
    if ctx is None or not self._config.llm_governance_enabled:
        return
    if usage:
        ctx.accumulate(usage)
        cost = estimate_usage_cost(model, canonical_from_dict(usage), provider=provider, base_url=base_url)
        ctx.add_cost(cost)
    self._safe_log_llm_event(ctx, usage, model, provider, api_duration)
```

### Phase 2B — Budget Enforcement (Requires Hermes `GovernanceBlock`)

Register `llm_execution` middleware:

```python
ctx.register_middleware("llm_execution", _PLUGIN.llm_execution_middleware)
```

The middleware callback:
```python
def llm_execution_middleware(
    self,
    request: dict,
    next_call,
    session_id: str = "",
    model: str = "",
    provider: str = "",
    base_url: str = "",
    **_,
) -> Any:
    if not self._config.llm_governance_enforcement_enabled:
        return next_call(request)

    exec_ctx = self._exec_context.get(session_id)
    if exec_ctx:
        decision = self._evaluate_llm_budget(exec_ctx, model, provider)
        if decision == "block":
            raise GovernanceBlock("LLM call blocked: budget exceeded")
        if decision == "hitl":
            self._notify_user("Execution paused pending approval in AMP.")
            resolution = self._await_hitl_decision(exec_ctx)
            if resolution not in {"approve", "approved", "modify", "modified"}:
                raise GovernanceBlock("LLM call blocked: HITL review rejected")

    response = next_call(request)
    return response
```

---

## 9. Execution-Context Design

### 9.1 Structure

AHP will maintain an in-memory `ExecutionContext` per session in a dict keyed by `session_id`. This dict is held on the `AmpGovernancePlugin` singleton instance.

```python
@dataclass
class LlmCallRecord:
    api_request_id: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    cost_usd: float
    cost_status: str            # "estimated" | "unknown" | "included"
    api_duration: float
    timestamp: str

@dataclass
class ExecutionContext:
    session_id: str
    instance_id: str            # AMP agent instance ID
    model: str
    platform: str
    created_at: str

    # Accumulated counters
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    total_cost_usd: float = 0.0
    cost_status: str = "unknown"
    llm_calls: int = 0
    tool_calls: int = 0

    # Plan governance (Phase 3)
    approved_budget_usd: float | None = None
    work_units_total: int = 0
    work_units_completed: int = 0

    # History (for audit)
    llm_call_records: list[LlmCallRecord] = field(default_factory=list)

    # Status
    status: str = "running"     # "running" | "hitl_pending" | "finished" | "blocked"
```

### 9.2 Lifecycle

- **Created:** in `on_session_start` (already exists), extended to also create `ExecutionContext`
- **Updated:** in `post_api_request` hook after each LLM call; in `post_tool_call` hook for tool count
- **Checked:** in `llm_execution` middleware (Phase 2B) before each LLM call
- **Finalized:** in `on_session_finalize` (already exists) — log totals to AMP, clear context

### 9.3 Concurrent Sessions

The `session_id` → `ExecutionContext` dict must be protected by a `threading.Lock` since hooks run in executor threads. The `SessionStore` already uses a `threading.Lock` as a model.

### 9.4 Subagent Association

When `subagent_start` fires, the parent `session_id` and child session details are available. AHP can link the child's `ExecutionContext` to the parent via `parent_session_id`. `post_api_request` hooks fire within the child's execution context (task-local), so child usage is automatically accumulated in the child's `ExecutionContext`. The parent's final report can sum child totals from the linked context.

### 9.5 Survival Across Process Restart

In Phase 1 and 2, execution context is in-memory only. A process restart clears it. For a HITL-paused execution, process restart means the pause is lost and the AMP workitem has no callback. This is acceptable for the initial implementation (in-process HITL). A durable continuation mechanism is a Phase 2 stretch goal, not a blocker.

### 9.6 Cleanup

`on_session_finalize` removes the `ExecutionContext` from the dict. If finalize never fires (process crash), the context leaks until restart. This is acceptable for the initial implementation.

---

## 10. Pause and Resume Design

### 10.1 How Pause Works Today

Current HITL pause is in `_evaluate_governance()` (`hermes/__init__.py:196–237`):
1. After AMP returns `status=pending`, the hook thread calls `time.sleep(poll_interval)` in a loop.
2. The agent's executor thread is blocked for the duration.
3. The asyncio event loop continues (other sessions' messages are handled).
4. When AMP returns a resolution, the loop exits and the hook returns `None` (allow) or a block dict.

### 10.2 Timeout Risk

The gateway inactivity timeout (`HERMES_AGENT_TIMEOUT`, default 1800s) monitors agent activity. The `_touch_activity()` call is made on tool calls and API calls. During HITL polling, there is no activity touch — the execution is frozen in the hook thread. This means a HITL review taking longer than 30 minutes will trigger the inactivity timeout and kill the execution.

**Mitigation (AHP-side, no Hermes change):** In the HITL polling loop, call `_safe_log()` every few minutes. The log call makes an HTTP request to AMP, which keeps the gateway alive if the session has a configurable activity extension. This is imperfect.

**Better mitigation (Hermes change, optional):** Add `agent._touch_activity()` to the hook invocation path, or expose it to plugins. This is a low-priority enhancement.

**Recommended for now:** Set `HERMES_AGENT_TIMEOUT=7200` (2 hours) in deployments that use HITL. Document this requirement.

### 10.3 Phase 2B Pause (LLM Call)

Same mechanism as Phase 1 (tool call) — sleep in the `llm_execution` middleware callback. Same timeout risk applies.

### 10.4 Cancellation and Interruption

If the user interrupts the Hermes session (sends a new message or `/interrupt`) while paused:
- The gateway sets `agent._interrupt_requested = True`
- The executor thread is blocked in the polling loop and will not observe the interrupt flag immediately
- The interrupt flag is checked at the top of the agent loop, but not inside hook callbacks

**Current gap:** An interrupt during HITL polling cannot cancel the polling loop. The execution will either time out or resume when AMP resolves the workitem.

**Recommended approach for Phase 1/2:** This is acceptable. HITL waits are expected to be short (< 10 minutes). Document that Hermes interrupts during HITL pause will not take effect until the HITL resolves or times out.

---

## 11. Token and Cost Accounting Design

### 11.1 Normalized Usage Structure

AHP will use a subset of Hermes' `CanonicalUsage` structure, converted to a plain dict for AMP logging:

```json
{
    "provider": "anthropic",
    "model": "claude-opus-4-8",
    "input_tokens": 1200,
    "output_tokens": 450,
    "cache_read_tokens": 8000,
    "cache_write_tokens": 0,
    "reasoning_tokens": 0,
    "total_tokens": 9650,
    "cost_usd": 0.0174,
    "cost_status": "estimated",
    "cost_source": "official_docs_snapshot",
    "api_call_number": 3,
    "api_duration_seconds": 2.1
}
```

`cost_status` mirrors Hermes' `CostStatus`: `"actual"`, `"estimated"`, `"included"`, `"unknown"`.

### 11.2 Cost Calculation Strategy

AHP will call `agent.usage_pricing.estimate_usage_cost()` directly in its `post_api_request` hook. This function is importable from within the plugin and does not require an agent reference.

```python
from agent.usage_pricing import CanonicalUsage, estimate_usage_cost

def _calc_cost(usage_dict: dict, model: str, provider: str, base_url: str) -> tuple[float, str, str]:
    cu = CanonicalUsage(
        input_tokens=usage_dict.get("input_tokens", 0),
        output_tokens=usage_dict.get("output_tokens", 0),
        cache_read_tokens=usage_dict.get("cache_read_tokens", 0),
        cache_write_tokens=usage_dict.get("cache_write_tokens", 0),
        reasoning_tokens=usage_dict.get("reasoning_tokens", 0),
    )
    result = estimate_usage_cost(model, cu, provider=provider, base_url=base_url)
    cost = float(result.amount_usd or 0.0)
    return cost, result.status, result.source
```

### 11.3 Unknown and Local Models

When `estimate_usage_cost()` returns `status="unknown"`, AHP records `cost_usd=0.0, cost_status="unknown"`. Budget enforcement (Phase 2B) should not trigger a block on `unknown` cost unless the user explicitly configures strict unknown-cost handling.

### 11.4 OpenRouter and Provider-Reported Cost

OpenRouter sometimes reports a `cost` field in the response headers or body. This is not captured by the current `post_api_request` `usage` dict. For OpenRouter, the cost may be `cost_status="estimated"` from the Hermes pricing table. Direct `provider_reported` cost is not available through the current hook interface.

If direct cost is needed, it can be obtained from the `response` dict in `post_api_request` by inspecting response-specific fields. This is a Phase 2 enhancement.

### 11.5 Streaming Usage

Streaming responses accumulate usage in `chat_completion_helpers.py` via `usage_obj = chunk.usage` on the final streaming chunk (lines 1890–1891 and 2000–2001). The `post_api_request` hook fires after streaming completes with the accumulated usage. No special streaming handling is needed in AHP.

### 11.6 Failed and Retried Calls

The `api_request_error` hook fires on failed calls. A retried call generates a second `pre_api_request` / `post_api_request` pair. The `api_call_count` kwarg increments per attempt. AHP should count and accumulate each call attempt, since tokens may have been consumed before the error.

---

## 12. AMP Policy and HITL Integration

### 12.1 What AMP Already Supports (No Changes Needed)

| Capability | AMP endpoint | Status |
|---|---|---|
| Policy evaluation (eval-policy) | `POST /api/hitl/request` | Exists (line 7474) |
| HITL request creation | `POST /api/hitl/request` | Exists |
| HITL decision polling | `GET /api/hitl/get-decision` | Exists (line 7798) |
| Instance init | `POST /api/agent/init` | Exists |
| Log events | `POST /api/log` | Exists (line 8697) |
| Instance state update | `POST /api/agent/setState` | Exists |
| Flat-field signal promotion | Built into policy routing | Exists (lines 7618–7622) |

**Flat-field promotion:** `app.py:7618–7622` shows that any flat top-level numeric, string, or boolean field in the `/api/hitl/request` payload that is not a reserved field name is automatically promoted to `params` for eval-policy evaluation. This means AHP can add `current_cost_usd`, `input_tokens`, `output_tokens`, `approved_budget_usd`, etc. to the request payload without any AMP schema change, and policy rules can reference these fields immediately.

### 12.2 AMP Eval-Policy Outcomes

Current AMP responses to `/api/hitl/request`:

| Status value | AHP interpretation |
|---|---|
| `"no_policy"` | Block (no active policy for agent) |
| `"no-hitl"` / `"allow"` / `"allowed"` / `"approved"` | Allow |
| `"pending"` / `"waiting-for-response"` + `workitem_id` | HITL required — pause and poll |
| Unexpected status + `fail_closed=True` | Block |

No changes to AMP needed.

### 12.3 Passing Cost/Token Signals to AMP

For Phase 2, AHP sends pre-call signals as flat top-level fields:

```python
payload = {
    "caller_id": instance_id,
    "instance_id": instance_id,
    "org_id": self._config.org_id,
    "agent_name": self._config.agent_name,
    "tool": "llm",
    "action": "call",
    "context": {"model": model},
    "hitl": {"enable": True, "when": "policy"},
    # Governance signals — promoted to params by AMP automatically
    "current_cost_usd": exec_ctx.total_cost_usd,
    "approved_budget_usd": exec_ctx.approved_budget_usd or 0.0,
    "estimated_next_call_cost_usd": estimated_next,
    "input_tokens_total": exec_ctx.input_tokens,
    "output_tokens_total": exec_ctx.output_tokens,
    "llm_calls_total": exec_ctx.llm_calls,
}
```

### 12.4 Approved Budget Flow (Phase 3A)

When AMP approves a plan, the HITL resolution or approval message can include a budget field in the `information` string. AHP extracts this from the HITL decision response and stores it in `ExecutionContext.approved_budget_usd`.

For a more structured flow, AMP could return a budget field in the `/api/hitl/get-decision` response. This would require a small AMP change to the decision payload, which the user should review before implementation.

### 12.5 Execution Correlation

AHP currently uses the AMP `instance_id` (one per Hermes session) as the correlation key. For Phase 3A (plan governance), a new `execution_id` field should be added to each LLM-call log event so AMP can correlate plan evaluation, runtime evaluations, tool calls, and the final result. AHP generates this ID (`uuid4()`) on session start.

---

## 13. Backward-Compatibility Strategy

### 13.1 Proposed Configuration Block

To be read from `~/.hermes/.env` (alongside existing AMP vars):

```dotenv
# Existing required vars (unchanged)
AMP_BACKEND_URL=...
AMP_API_KEY=...
AMP_ORG_ID=...
AMP_USERNAME=...
AMP_AGENT_NAME=...

# Existing optional vars (unchanged)
AMP_HITL_TIMEOUT_MINUTES=10
AMP_HITL_POLL_INTERVAL_SECONDS=3
AMP_FAIL_CLOSED=true

# Phase 1: Notification bridge (new, defaults off until generalization ships)
# No new config needed — auto-detects platform from session context

# Phase 2: LLM usage governance (new, all off by default)
AMP_LLM_GOVERNANCE_ENABLED=false
AMP_LLM_GOVERNANCE_MODE=observe          # observe | enforce
AMP_LLM_GOVERNANCE_FAIL_CLOSED=false     # if AMP unreachable: fail-open for LLM calls
AMP_LLM_GOVERNANCE_INCLUDE_SUBAGENTS=true
```

This preserves all existing behavior. Users who do not add the new variables experience zero change.

### 13.2 Migration and Defaults

| Setting | Default | Behavior with default |
|---|---|---|
| `AMP_LLM_GOVERNANCE_ENABLED` | `false` | No LLM governance hooks fire |
| `AMP_LLM_GOVERNANCE_MODE` | `observe` | Even when enabled, no blocking |
| `AMP_LLM_GOVERNANCE_FAIL_CLOSED` | `false` | If AMP is unreachable for LLM governance, allow the call |

Tool-call governance (`fail_closed`) defaults remain `true` as today.

### 13.3 Fail Behavior by Mode

| Mode | AMP unreachable | AMP returns unexpected |
|---|---|---|
| Tool governance | `AMP_FAIL_CLOSED` (default `true`) = block | Block if fail_closed |
| LLM governance (observe) | Log warning, continue | Log warning, continue |
| LLM governance (enforce) | `AMP_LLM_GOVERNANCE_FAIL_CLOSED` (default `false`) = allow | Allow if fail-open |

### 13.4 Latency Impact

- **Phase 1 (notification):** Notification is fire-and-forget (no additional latency to governance path). `dispatch_tool("send_message")` is synchronous but fast (< 500ms). On failure, it is swallowed immediately.
- **Phase 2A (observe):** `post_api_request` hook is observer-only. `estimate_usage_cost()` is a pure function (no network). AMP log call is async fire-and-forget via `_safe_log()`. Zero additional latency on the hot path.
- **Phase 2B (enforce):** Adds one `POST /api/hitl/request` call before each LLM call. Typical latency: 100–300ms. Must be opt-in.

---

## 14. Risks and Unresolved Questions

### 14.1 High-Risk Technical Issues

**R1 — Middleware block propagation (Highest risk)**  
`llm_execution` middleware cannot block by raising `Exception`. The `GovernanceBlock(BaseException)` approach requires a two-file Hermes change. If this change is rejected or delayed, Phase 2B enforcement cannot be implemented cleanly. Fallback: use a mutable flag (hacky) or skip LLM-level enforcement in Phase 2, relying only on tool-call blocking.

**R2 — Gateway inactivity timeout kills paused executions**  
A HITL review exceeding 30 minutes (default) will kill the waiting execution. The user has no visible warning. Mitigation: document and recommend raising `HERMES_AGENT_TIMEOUT`.

**R3 — `send_message` tool requires live gateway**  
`_dispatch_tool("send_message")` requires a running gateway adapter. In CLI mode, it silently no-ops. This is acceptable but must be documented.

**R4 — `post_api_request` usage dict may be `None`**  
If the provider does not return usage (e.g., some Ollama models, custom servers), `usage` in `post_api_request` is `None`. AHP must handle `None` gracefully and record `cost_status="unknown"`.

**R5 — Subagent cost attribution**  
`post_api_request` hooks fire inside the subagent's execution context. AHP's `ExecutionContext` for the parent session will NOT see subagent costs unless subagents are also AHP-governed with the same AMP instance. The `subagent_start`/`subagent_stop` hooks provide session linkage but not cost data directly.

### 14.2 Product-Owner Decisions Required

1. **Should AMP return an approved budget in the HITL resolution payload?** A structured budget field (e.g., `{"approved_budget_usd": 5.0}`) in the `/api/hitl/get-decision` response would simplify Phase 3A. Currently the only mechanism is parsing the `information` string. **This would require a small AMP change.**

2. **Should the inactivity timeout be raised automatically when HITL is pending?** This requires a Hermes change. The simpler path is to document and require manual env-var configuration.

3. **What should happen when AMP is unreachable during LLM governance enforcement?** Fail-open (allow call) is proposed as the default for LLM governance. Is this acceptable, or should LLM governance default to fail-closed like tool governance?

4. **Should `GovernanceBlock` be contributed back to Hermes upstream?** This change benefits any governance plugin (not just AMP), making it a good upstream contribution candidate.

5. **What is the expected latency budget for a pre-LLM policy call?** One AMP round trip (100–300ms per call) before every LLM invocation. For a 10-call execution, this adds 1–3 seconds of total latency. Is this acceptable?

6. **For Phase 3A, what plan fields does the AMP policy engine need?** The generic plan submission format must be agreed before implementation.

---

## 15. Proposed Development Phases

### Phase 1A — Notification Bridge Generalization (AHP only)

1. Replace `_build_slack_target()` and `_notify_slack()` with `_build_notification_target()` and `_notify_user()` as designed in §6.
2. Test with Slack (regression), Telegram, and CLI.
3. Update `plugin.yaml` to document notification behavior.
4. No Hermes change.

**Estimated effort:** 1–2 days (mostly tests).

### Phase 1B — AHP Notification States

1. Add `_notify_user()` calls for all governance state transitions: `paused`, `resumed`, `rejected`, `timed_out`, `blocked`, `completed`.
2. Add config option to disable notifications (`AMP_NOTIFICATIONS_ENABLED=true`).
3. Test all notification states.

**Estimated effort:** 1 day.

### Phase 2A — LLM Usage Observation

1. Add `ExecutionContext` dataclass and in-memory store to `AmpGovernancePlugin`.
2. Register `post_api_request` hook.
3. In hook: call `estimate_usage_cost()`, update `ExecutionContext`, log to AMP.
4. In `on_session_finalize`: log summary totals to AMP, clean up context.
5. Extend `SessionRecord` or add separate model to track execution ID.
6. Gated by `AMP_LLM_GOVERNANCE_ENABLED`.
7. No Hermes change.

**Estimated effort:** 2–3 days.

### Phase 2B — Runtime Budget Enforcement

**Prerequisite:** Hermes `GovernanceBlock` change merged and deployed.

1. Register `llm_execution` middleware.
2. Before `next_call`: read `ExecutionContext`, send signals to AMP policy, receive decision.
3. If `hitl`: pause (sleep loop), notify user, poll for resolution, resume or raise `GovernanceBlock`.
4. If `block`: raise `GovernanceBlock`.
5. After `next_call`: update `ExecutionContext` with actual response usage.
6. Gated by `AMP_LLM_GOVERNANCE_MODE=enforce`.

**Estimated effort:** 3–4 days plus Hermes change coordination.

### Phase 3A — Generic Plan Governance

1. Add `evaluate_proposed_plan(plan: dict) -> PlanDecision` method to `AmpGovernancePlugin`.
2. Normalize plan fields to AMP policy signals.
3. Call `/api/hitl/request` with plan as context.
4. Handle HITL, budget extraction, and decision return.
5. Initialize `ExecutionContext.approved_budget_usd` from decision.

**Estimated effort:** 3–4 days.

### Phase 3B — Research Agent Sample

Separate implementation (not in AHP). Uses Phase 3A plan governance interface.

### Phase 4 - AHP Launch Polish

Once the Hermes upstream improvement at GitHub is released and merged into AHP, we will revisit the below items for AHP launch readiness. This should be done before AMP SaaS release on Aug 31, 2026.

* Pointer skill installation
* Agent Log richness
* Demo walkthrough
* Screen recording
* First-run experience
* README refinements
* Automatic installation opportunities
* Governance summary presentation
* Cron documentation
* Manual end-to-end validation

---

## 16. File-by-File Implementation Plan

### AHP Files to Modify

| File | Change |
|---|---|
| `hermes/__init__.py` | Replace `_notify_slack()` / `_build_slack_target()` with platform-neutral `_notify_user()` / `_build_notification_target()`; add `ExecutionContext` dict; add `post_api_request` hook method; add `llm_execution` middleware method; update `register()` |
| `hermes/config.py` | Add `llm_governance_enabled`, `llm_governance_mode`, `llm_governance_fail_closed` to `AmpConfig` |
| `hermes/amp_client.py` | Add `log_llm_event(instance_id, usage_dict)` method; add budget signal fields to `request_hitl` payload |
| `hermes/session_store.py` | Add `execution_id` field to `SessionRecord` |
| `plugin.yaml` | Add `post_api_request` to hooks list |

### New AHP Files

| File | Content |
|---|---|
| `hermes/execution_context.py` | `ExecutionContext` dataclass; `LlmCallRecord`; accumulation helpers |
| `hermes/notification.py` | `_build_notification_target()`, `_notify_user()` |

### Hermes Files to Modify (Phase 2B only)

| File | Change | Size |
|---|---|---|
| `hermes_cli/middleware.py` | Add `GovernanceBlock(BaseException)` class | ~10 lines |
| `agent/conversation_loop.py` | Catch `GovernanceBlock` around `run_llm_execution_middleware(...)` | ~12 lines |

---

## 17. Testing Strategy

### Unit Tests (AHP test suite)

| Test | File |
|---|---|
| `_build_notification_target()` returns correct format for Slack, Telegram, Discord, CLI | `tests/test_plugin.py` |
| `_notify_user()` is no-op when `dispatch_tool` is None | `tests/test_plugin.py` |
| `_notify_user()` is no-op in CLI (no platform) | `tests/test_plugin.py` |
| `_notify_user()` failure does not propagate | `tests/test_plugin.py` |
| `ExecutionContext.accumulate()` with full usage | `tests/test_execution_context.py` |
| `ExecutionContext.accumulate()` with None usage | `tests/test_execution_context.py` |
| `post_api_request` hook accumulates across 3 calls | `tests/test_plugin.py` |
| `post_api_request` hook with unknown cost | `tests/test_plugin.py` |
| `post_api_request` hook skipped when `llm_governance_enabled=False` | `tests/test_plugin.py` |
| Existing tool governance tests unchanged | `tests/test_plugin.py`, `tests/test_policy.py` |
| Config loading with all new vars | `tests/test_config.py` |

### Integration Tests

| Scenario | Expected |
|---|---|
| Slack session: tool HITL → notification sent to thread | Notification sent to `slack:C...:thread_id` |
| Telegram session: tool HITL → notification sent | Notification sent to `telegram:chat:thread` |
| CLI session: tool HITL → no notification sent, governance still enforced | No crash; block still works |
| Tool governance with notifications disabled | No notification; block still works |
| LLM call observed: usage accumulated in ExecutionContext | Totals correct after 3 calls |
| LLM call observed: None usage handled gracefully | No crash; cost_status="unknown" |
| Streaming LLM call observed: usage still captured | Totals correct (streaming completes before hook fires) |
| Retry: failed LLM call logs api_request_error; retried call accumulates separately | Two records; totals sum both |
| AMP unavailable (LLM observe mode): log warning, allow | No crash; execution continues |
| AMP unavailable (LLM enforce mode, fail-open): allow | No crash; call proceeds |
| AMP unavailable (tool mode, fail-closed): block | Block returned as today |
| HITL approve: execution resumes, notification sent | Correct notification text |
| HITL reject: execution blocked, notification sent | Correct block message |
| HITL timeout: block, notification sent | Correct timeout message |
| Concurrent sessions: ExecutionContext isolated per session_id | No cross-session accumulation |
| Session finalize: ExecutionContext cleaned up | No memory leak across 100 sessions |
| Process restart during HITL: new session starts cleanly | No crash; stale ExecutionContext gone |

---

## 18. Acceptance Criteria — Phase 1

1. `_notify_user()` sends to the originating Slack thread, Telegram topic, Discord channel, and Signal chat.
2. `_notify_user()` is a no-op in CLI mode without any warning or error.
3. `_notify_user()` delivery failure does not affect governance enforcement.
4. Tool-call HITL triggers a `"paused"` notification.
5. HITL approval triggers a `"resumed"` notification.
6. HITL rejection triggers a `"rejected"` notification.
7. HITL timeout triggers a `"timed_out"` notification.
8. All existing tool-governance tests pass unchanged.
9. The notification system is functional when `AMP_BACKEND_URL` and all required config vars are set.
10. The notification system fails gracefully (no crash) when `send_message` tool is not available.

---

## 19. Acceptance Criteria — Phase 2

### Phase 2A (Observation)

1. `post_api_request` hook accumulates `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens` per session.
2. Cost is estimated via `estimate_usage_cost()` and accumulated per session.
3. When usage is `None` (provider does not report tokens), cost is recorded as `0.0` with `cost_status="unknown"`. No crash.
4. Streaming calls report usage correctly (same as non-streaming).
5. Retried calls each contribute a separate record; totals reflect all attempts.
6. `on_session_finalize` logs a summary event to AMP with final totals.
7. All of the above is disabled when `AMP_LLM_GOVERNANCE_ENABLED=false` (default).
8. No measurable latency increase when Phase 2A is enabled (all operations are local or fire-and-forget).

### Phase 2B (Enforcement)

1. When `AMP_LLM_GOVERNANCE_MODE=enforce` and AMP policy returns `block`, the LLM call does not proceed and the user receives a governance block message.
2. When AMP policy returns `hitl`, the LLM call is paused, the user receives a notification, and execution waits for a decision.
3. HITL approval resumes the LLM call and all subsequent execution.
4. HITL rejection causes the LLM call to return a blocked response.
5. When AMP is unreachable and `AMP_LLM_GOVERNANCE_FAIL_CLOSED=false` (default), the LLM call proceeds normally.
6. All of the above is disabled when `AMP_LLM_GOVERNANCE_ENABLED=false` (default).
7. Tool-call governance behavior is unchanged.
8. `GovernanceBlock` is raised cleanly and caught by the conversation loop without crashing other sessions.

---

## 20. Hermes Upstream Contribution Recommendation

The `GovernanceBlock(BaseException)` change and the corresponding `except GovernanceBlock` handler in `agent/conversation_loop.py` should be proposed as a Hermes upstream contribution for the following reasons:

1. It solves a general problem (governance plugins needing to block LLM calls) that is not AMP-specific.
2. The change is small, well-scoped, and non-breaking.
3. It enables a class of security and compliance plugins that cannot currently exist.
4. Contributing upstream avoids maintaining a Hermes fork.

The contribution should include:
- `GovernanceBlock` class in `hermes_cli/middleware.py`
- Exception handler in `agent/conversation_loop.py`
- A test in the Hermes test suite
- Documentation in `AGENTS.md` and `hermes_cli/plugins.py` docstring for `register_middleware`

**All other changes are AHP-only and do not require upstream contribution.**

---

## Final Summary

### Recommended Architecture

AHP extends in three rings:

1. **Notification bridge (Phase 1):** Generalize `_notify_slack()` to `_notify_user()` using `get_session_env("HERMES_SESSION_PLATFORM")` and the existing cross-platform `send_message` tool. AHP-only change.

2. **LLM usage observation (Phase 2A):** Register `post_api_request` hook. Accumulate canonical usage into an `ExecutionContext` per session. Call `estimate_usage_cost()` locally. Log to AMP. AHP-only change, default off.

3. **Budget enforcement (Phase 2B):** Register `llm_execution` middleware. Call AMP policy before each LLM call. Pause/resume via HITL polling (same thread-sleep mechanism as current tool HITL). Requires `GovernanceBlock(BaseException)` in Hermes (small targeted change to two files). Default off.

### Phase 1 Status

**Phase 1 can be implemented entirely within AHP.** No Hermes core change required.

### Phase 2 Status

**Phase 2A (observation) requires no Hermes change.** Phase 2B (enforcement) requires the `GovernanceBlock` change in two Hermes files (~22 lines total). This is the only required Hermes change across all phases.

### Highest-Risk Technical Issue

**R1 — Middleware block propagation.** If the `GovernanceBlock` Hermes change cannot be merged, Phase 2B enforcement cannot be implemented cleanly. All other risks are manageable within AHP.

### First Pull Request Scope

Phase 1A + 1B combined:
- Generalize notification bridge to all platforms
- Add `_notify_user()` with all governance event types
- Update tests to cover Slack, Telegram, Discord, and CLI cases
- Update `plugin.yaml` to list all hooks
- No Hermes change, no new dependencies, no behavior change for existing users

### Decisions Required Before Coding

1. Approval to open a Hermes upstream PR for `GovernanceBlock` (required for Phase 2B).
2. Confirm `HERMES_AGENT_TIMEOUT` configuration responsibility (AHP docs or Hermes default change).
3. Confirm whether AMP should return a structured `approved_budget_usd` field in HITL decisions (AMP change, required for Phase 3A clean design).
4. Confirm acceptable per-LLM-call latency overhead for Phase 2B enforcement (expected: 100–300ms).
5. Confirm fail-open vs fail-closed default for LLM governance (proposed: fail-open, unlike tool governance which defaults fail-closed).
