# Hermes AMP Governance Plugin

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

AMP governance plugin for Hermes.

This plugin connects a Hermes agent to AMP so AMP can:

- log prompts and governed tool activity
- evaluate tool calls against an AMP `eval-policy`
- require HITL approval when the policy says so
- block governed actions when AMP rejects them
- add date-aware routing context for time-sensitive prompts so Hermes is more likely to use `web_search` for current information
- send governance notifications back to the originating channel on any platform
- observe and record LLM token usage and estimated cost per session (opt-in)

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

## LLM usage observation (Phase 2A)

When enabled, the plugin observes every LLM API call and accumulates token usage and estimated cost per session. Observation runs in both `observe` and `enforce` modes.

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

## Prerequisites

Before installing this plugin, make sure you already have:

- Hermes installed and running on your machine
- a working Hermes channel or chat surface, such as Slack, Telegram, or Discord
- an AMP environment available, such as:
  - `https://amp.inquiryon.com`, or
  - a local AMP dev instance
- an AMP agent created for Hermes
- the following AMP values:
  - `AMP_BACKEND_URL`
  - `AMP_API_KEY`
  - `AMP_ORG_ID`
  - `AMP_AGENT_NAME`
  - `AMP_USERNAME`

## Files you need from this repo

Create one plugin folder under your Hermes home:

- default Hermes home: `~/.hermes`
- plugin folder: `~/.hermes/plugins/amp-governance`

Copy these files from this repo into that folder:

- `plugin.yaml`
- `__init__.py`
- `amp_client.py`
- `config.py`
- `execution_context.py`
- `notification.py`
- `policy.py`
- `session_store.py`

The final layout should look like this:

```text
~/.hermes/
  plugins/
    amp-governance/
      plugin.yaml
      __init__.py
      amp_client.py
      config.py
      execution_context.py
      notification.py
      policy.py
      session_store.py
```

## Install options

### Option A — copy files

Use this when you want a normal local install from a downloaded repo snapshot.

```bash
mkdir -p ~/.hermes/plugins/amp-governance

cp /path/to/amp-hermes-plugin/plugin.yaml ~/.hermes/plugins/amp-governance/
cp /path/to/amp-hermes-plugin/__init__.py ~/.hermes/plugins/amp-governance/
cp /path/to/amp-hermes-plugin/amp_client.py ~/.hermes/plugins/amp-governance/
cp /path/to/amp-hermes-plugin/config.py ~/.hermes/plugins/amp-governance/
cp /path/to/amp-hermes-plugin/execution_context.py ~/.hermes/plugins/amp-governance/
cp /path/to/amp-hermes-plugin/notification.py ~/.hermes/plugins/amp-governance/
cp /path/to/amp-hermes-plugin/policy.py ~/.hermes/plugins/amp-governance/
cp /path/to/amp-hermes-plugin/session_store.py ~/.hermes/plugins/amp-governance/
```

### Option B — symlink the repo

Use this when you are developing the plugin locally and want edits to take effect from the repo.

```bash
mkdir -p ~/.hermes/plugins
ln -s /path/to/amp-hermes-plugin ~/.hermes/plugins/amp-governance
```

## Step 1 — enable the plugin

Before configuring AMP governance, first install Hermes in your environment and verify that Hermes is working correctly. Once Hermes is running successfully, enable this plugin:

```bash
hermes plugins enable amp-governance
```

## Step 2 — register your Hermes agent in AMP

Before this plugin can govern Hermes, your Hermes agent must be registered in AMP.

If you are using AMP UI:

1. Create a user account at amp.inquiryon.com if you haven't done so.
2. Login to AMP (amp.inquiryon.com).
3. Go to **Agent Launchpad**
4. Create / register a new remote agent for Hermes.
5. Use a name or put in a description that relates to Hermes so that AMP AI can help you select a relevant policy.
6. Select **Allow auto-start** at the Registration popup.
7. Click **Register**
8. Create an AMP API Key if you do not have one.
9. Copy the generated values for:
   - `AMP_API_KEY`
   - `AMP_AGENT_NAME`

## Step 3 — add AMP settings to Hermes

Copy `.env.example` into your Hermes home as `~/.hermes/.env`, then fill in your real AMP values:

```env
AMP_BACKEND_URL=https://amp.inquiryon.com
AMP_USERNAME=your_name@email_domain.com
AMP_API_KEY=amp_k_...
AMP_ORG_ID=O-0011-AB202605010...
AMP_AGENT_NAME=your-hermes-agent-10c8
```

You can find your username and org_id in **My Profile** on the side menu in AMP.

Optional settings:

```env
# HITL behavior
AMP_HITL_TIMEOUT_MINUTES=10
AMP_HITL_POLL_INTERVAL_SECONDS=3
AMP_FAIL_CLOSED=true

# Notification bridge (default: on)
AMP_NOTIFICATIONS_ENABLED=true

# LLM usage observation and enforcement (default: off)
AMP_LLM_GOVERNANCE_ENABLED=false
# "observe" = token/cost accumulation only; "enforce" = pre-call policy eval + block
AMP_LLM_GOVERNANCE_MODE=observe
# fail-open by default: allow LLM calls if AMP is unreachable (false=fail-open)
AMP_LLM_GOVERNANCE_FAIL_CLOSED=false
AMP_LLM_GOVERNANCE_INCLUDE_SUBAGENTS=true
```

Notes:

- `AGENT_NAME` is accepted as a fallback alias for `AMP_AGENT_NAME`
- `AMP_FAIL_CLOSED=true` is recommended for governance-focused deployments
- `AMP_NOTIFICATIONS_ENABLED=true` is the default; notifications go to whatever channel the user is in
- `AMP_LLM_GOVERNANCE_ENABLED=false` is the default; set to `true` to enable token/cost observation and enforcement
- `AMP_LLM_GOVERNANCE_MODE=enforce` requires Hermes with `LLMExecutionBlocked` ([hermes-agent#64662](https://github.com/nousresearch/hermes-agent/issues/64662))
- if you use a custom Hermes home, set `HERMES_HOME` and place `.env` under that directory
- for long HITL reviews (> 30 min), set `HERMES_AGENT_TIMEOUT=7200` to prevent the gateway from killing the waiting session

## Step 4 — restart Hermes gateway

Run:

```bash
hermes gateway restart
```

If the gateway is not running yet, start it the way you normally run Hermes.

## Step 5 — create or install an AMP eval policy

This plugin expects your Hermes AMP agent to have an active `eval-policy`.

At minimum, that policy should define rules for the normalized tool/action pairs listed above.

If you are using AMP UI:

1. Login to amp.inquiryon.com
2. Go to **Agent Launchpad**.
3. Open your Hermes agent created above by clicking on its tile.
4. On the side menu, under **Governance**, choose **Write New Policy**.
5. Choose **eval-policy**.
6. Click on the AI icon on the page and use AI to help suggest a Hermes policy sample.
7. Create and activate the policy by following the screen instruction.

## Step 6 — test the integration

Send a simple prompt to Hermes that should use a governed tool.

Examples:

- `Can you run git status in ~/Projects/my-repo?`
- `Can you read ~/Projects/my-repo/README.md?`
- `Can you search for files named policy.json under ~/Projects/agents/?`
- `How did the US market perform today?`
- `Please perform a web search for the latest news about social security fraud in the US.`

Expected behavior:

- AMP should log the Hermes session and tool activity
- safe actions should proceed normally
- time-sensitive or explicitly live-information prompts should be routed toward `web_search` using injected current-date context
- blocked actions should return:
  - `This request is blocked by AMP governance. No action was taken.`
- HITL actions should pause until a reviewer approves or rejects them in AMP
- when Hermes is running in a messaging surface (Slack, Telegram, Discord, etc.), the plugin posts a channel message when AMP is waiting for review and another message when the review is resolved

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

## Files in this plugin

- `plugin.yaml` — Hermes plugin manifest
- `__init__.py` — main plugin hooks and governance flow
- `amp_client.py` — AMP API client
- `config.py` — config loading from `~/.hermes/.env`
- `execution_context.py` — per-session LLM usage accumulation
- `notification.py` — platform-neutral notification bridge
- `policy.py` — Hermes tool normalization into AMP policy vocabulary
- `session_store.py` — session-to-AMP instance tracking
- `.env.example` — example environment variables for setup
- `LICENSE` — MIT open-source license

## Recommended first setup path

If you are setting this up for the first time, follow this order:

1. install Hermes and confirm your chat channel works
2. copy this plugin into `~/.hermes/plugins/amp-governance`
3. enable the plugin
4. create a Hermes agent in AMP
5. add AMP variables to `~/.hermes/.env`
6. restart Hermes gateway
7. activate an AMP `eval-policy` for the Hermes agent
8. test one safe command and one HITL-triggering command

## Development note

For local development, symlink install is easier because Hermes will load the plugin directly from your working repo:

```bash
ln -s /path/to/amp-hermes-plugin ~/.hermes/plugins/amp-governance
hermes plugins enable amp-governance
hermes gateway restart
```
