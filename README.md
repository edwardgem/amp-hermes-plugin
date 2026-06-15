# Hermes AMP Governance Plugin

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

AMP governance plugin for Hermes.

This plugin connects a Hermes agent to AMP so AMP can:

- log prompts and governed tool activity
- evaluate tool calls against an AMP `eval-policy`
- require HITL approval when the policy says so
- block governed actions when AMP rejects them

## What this plugin governs

Hermes tools are normalized into AMP policy vocabulary like this:

- `terminal` → `exec/exec`
- `read_file` → `read/read`
- `search_files` → `read/search`
- `write_file` → `write/write`
- `patch` → `write/edit`
- `web_search` → `exec/web_search`

## Prerequisites

Before installing this plugin, make sure you already have:

- Hermes installed and running on your machine
- a working Hermes channel or chat surface, such as Slack
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
AMP_HITL_TIMEOUT_MINUTES=10
AMP_HITL_POLL_INTERVAL_SECONDS=3
AMP_FAIL_CLOSED=true
```

Notes:

- `AGENT_NAME` is accepted as a fallback alias for `AMP_AGENT_NAME`
- `AMP_FAIL_CLOSED=true` is recommended for governance-focused deployments
- if you use a custom Hermes home, set `HERMES_HOME` and place `.env` under that directory

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

Expected behavior:

- AMP should log the Hermes session and tool activity
- safe actions should proceed normally
- blocked actions should return:
  - `This request is blocked by AMP governance. No action was taken.`
- HITL actions should pause until a reviewer approves or rejects them in AMP

## How to verify it is working

Check these places:

- Hermes gateway logs
- Hermes chat surface, such as Slack
- AMP agent log for the Hermes agent
- AMP workitems page if HITL is triggered

You should see AMP entries similar to:

- session started
- user prompt logged
- policy check for a normalized tool/action
- policy decision
- HITL requested, if approval is required

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

## Files in this plugin

- `plugin.yaml` — Hermes plugin manifest
- `__init__.py` — main plugin hooks and governance flow
- `amp_client.py` — AMP API client
- `config.py` — config loading from `~/.hermes/.env`
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
