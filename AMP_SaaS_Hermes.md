# Hermes Agent Governance With Inquiryon AMP — SaaS Edition

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

You're here because you're connecting Hermes to **Inquiryon AMP's SaaS
service** (`https://amp.inquiryon.com`). If you meant to self-host AMP
instead, go back to [`README.md`](README.md) and follow the OSS branch —
this page doesn't apply there.

This plugin (also referred to as the AMP-Hermes Plugin, or AHP) connects
a Hermes agent to AMP so AMP can:

- log prompts and governed tool activity
- evaluate tool calls against an AMP `eval-policy`
- require HITL (Human-in-the-Loop) approval when the policy says so
- block governed actions when AMP rejects them
- add date-aware routing context for time-sensitive prompts so Hermes is more likely to use `web_search` for current information
- notify the active Hermes channel when AMP is waiting for human review and when that review is resolved

If you already run Hermes, you can have this running in a few minutes.

## What You'll Experience

- ✅ Connect Hermes to AMP
- ✅ Experience runtime governance
- ✅ Observe policy evaluation
- ✅ Approve a HITL request
- ✅ View execution audit logs

```
            User
              │
              ▼
      Hermes AI Agent
              │
              ▼
      AMP-Hermes Plugin (AHP)
              │
              ▼
      AMP Governance Platform
      ┌────────┼────────┐
      ▼        ▼        ▼
   Policies   HITL   Audit Logs
```

## What this plugin governs

Hermes tools are normalized into AMP policy vocabulary like this:

- `terminal` → `exec/exec`
- `read_file` → `read/read`
- `search_files` → `read/search`
- `write_file` → `write/write`
- `patch` → `write/edit`
- `web_search` → `exec/web_search`

## Additional behavior

Besides tool governance, the plugin also improves two parts of the Hermes user experience:

- for prompts that appear time-sensitive or explicitly ask for live information, the plugin injects current-date context and tells Hermes to use `web_search` instead of answering from memory
- when AMP triggers HITL, the plugin uses Hermes `send_message` to notify the active channel that the action is waiting for human review, then posts a follow-up when the reviewer approves, modifies, rejects, or times out the request

## Prerequisites

Before installing this plugin, make sure you already have:

- Hermes installed and running on your machine — see [`README.md`](README.md)'s Prerequisites if you haven't done this yet
- a working Hermes channel or chat surface, such as Slack
- an AMP SaaS account at `https://amp.inquiryon.com`

## Quick Start

**1. Register a Hermes Remote Agent in AMP** — in the AMP UI:

> **Tip:** Use the **AMP Quick Start** wizard to auto-complete Steps 1-3
> below (recommended).

If you'd rather do it manually, or aren't using AMP UI: log in to AMP →
**Agent Launchpad** → register a new **remote agent** for Hermes
(mention "Hermes" in the agent name or description so AMP AI can
recommend a relevant policy) → check **Allow auto-start** → **Register**.

**2. Create (or use) an AMP API Key** — open the side menu → **Settings**
to copy an existing API key or create a new one.

**3. Attach a governance policy** — on the **Agent Launchpad** page, open
your registered agent. On the side menu, under **Governance** → **Write
New Policy** → **Rule-based Policy** (also called eval-policy) → use the
AI icon to generate a starter Hermes policy → activate it. This step
should define rules for the normalized tool/action pairs listed above.

You now have `AMP_API_KEY` and `AMP_AGENT_NAME`. Find `AMP_ORG_ID` and
`AMP_USERNAME` under **My Profile**. Remember them for Step 5.

**4. Install the plugin** — on the machine where your Hermes agent runs,
run one command:

```bash
hermes plugins install inquiryon/amp-hermes-plugin/examples/saas --enable
```

This clones the repo, installs the `examples/saas/` subdirectory as the
`amp-governance` plugin, and enables it in one step.

<details>
<summary>Alternative: manual copy or symlink</summary>

Use manual copy for a normal local install from a downloaded repo
snapshot:

```bash
mkdir -p ~/.hermes/plugins/amp-governance

cp /path/to/amp-hermes-plugin/examples/saas/plugin.yaml ~/.hermes/plugins/amp-governance/
cp /path/to/amp-hermes-plugin/examples/saas/__init__.py ~/.hermes/plugins/amp-governance/
cp /path/to/amp-hermes-plugin/examples/saas/amp_client.py ~/.hermes/plugins/amp-governance/
cp /path/to/amp-hermes-plugin/examples/saas/config.py ~/.hermes/plugins/amp-governance/
cp /path/to/amp-hermes-plugin/examples/saas/policy.py ~/.hermes/plugins/amp-governance/
cp /path/to/amp-hermes-plugin/examples/saas/session_store.py ~/.hermes/plugins/amp-governance/

hermes plugins enable amp-governance
```

Use symlink instead if you're developing the plugin locally — see
"Local Development" at the bottom of this page.

</details>

**5. Configure environment variables** — add your AMP credentials to
`~/.hermes/.env` (or wherever your Hermes install directory is). Copy
`examples/saas/.env.example` as a starting point:

```env
AMP_BACKEND_URL=https://amp.inquiryon.com
AMP_USERNAME=your_name@email_domain.com
AMP_API_KEY=amp_k_...
AMP_ORG_ID=O-0011-AB202605010...
AMP_AGENT_NAME=your-hermes-agent-10c8
```

Optional settings:

```env
AMP_HITL_TIMEOUT_MINUTES=10
AMP_HITL_POLL_INTERVAL_SECONDS=3
AMP_FAIL_CLOSED=true
```

Notes:

- `AGENT_NAME` is accepted as a fallback alias for `AMP_AGENT_NAME`
- `AMP_FAIL_CLOSED=true` is recommended for governance-focused deployments
- if you use a custom Hermes home, set `HERMES_HOME` and place `.env` under that directory

**6. Restart Hermes:**

```bash
hermes gateway restart
```

If the gateway is not running yet, start it the way you normally run Hermes.

**7. Run your first governed command** — send this through your Hermes
channel:

- Log in to AMP and open **Agent Log** from the side menu. Then send
  this query on your Hermes channel: `Can you give me recent news on SS
  frauds?` — a plain governed tool call.

You should see transparency logs appear on the AMP **Agent Log** page,
and this query will trigger HITL approval before Hermes executes it. See
"Verify Everything Works" below to confirm it's genuinely governed, not
just running.

## Verify Everything Works

Check these places while (or after) running the command above:

**Hermes**

- The command pauses when approval is required, with a message like:
  - `[AMP] AMP is waiting for a human reviewer to approve "web_search" before continuing. This action is paused pending review.`
- Hermes receives an approval/rejection notification once a reviewer acts:
  - `[AMP] AMP reviewer approved "web_search". Continuing now.`
  - `[AMP] AMP reviewer rejected "web_search". ...`
- For time-sensitive prompts, Hermes uses `web_search` instead of answering only from model memory.

**AMP**

- The agent's activity log timeline shows entries like: session started, user prompt logged, policy check for a normalized tool/action, policy decision, and HITL requested (if approval is required).
- The workitems page shows a pending HITL item, if one was triggered. Click the workitem ID, or go to the Agent Worktray page, to approve the request.

🎉 **Congratulations! Your Hermes agent is now governed by AMP.**

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

## Developer Notes

### Files in this plugin

- `examples/saas/plugin.yaml` — Hermes plugin manifest
- `examples/saas/__init__.py` — main plugin hooks and governance flow
- `examples/saas/amp_client.py` — AMP API client
- `examples/saas/config.py` — config loading from `~/.hermes/.env`
- `examples/saas/policy.py` — Hermes tool normalization into AMP policy vocabulary
- `examples/saas/session_store.py` — session-to-AMP instance tracking
- `examples/saas/.env.example` — example environment variables for setup
- `LICENSE` — MIT open-source license

### Local Development

For local development, symlink install is easier than `hermes plugins
install` because Hermes will load the plugin directly from your working
repo, and edits take effect on the next gateway restart with no
reinstall step:

```bash
mkdir -p ~/.hermes/plugins
ln -s /path/to/amp-hermes-plugin/examples/saas ~/.hermes/plugins/amp-governance
hermes plugins enable amp-governance
hermes gateway restart
```
