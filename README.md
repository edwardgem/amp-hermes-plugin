# Hermes AMP Governance Plugin

Hermes-native AMP governance plugin for eval-policy enforcement.

## First milestone

- creates an AMP instance for a Hermes session
- logs user prompts and governed tool activity to AMP
- normalizes selected Hermes tools into AMP policy vocabulary
- enforces allow / block / HITL before execution
- replaces the final assistant reply with a fixed blocked message when AMP rejects a governed action

## Governed Hermes tools

- `terminal` → `exec/exec`
- `read_file` → `read/read`
- `search_files` → `read/search`
- `write_file` → `write/write`
- `patch` → `write/edit`
- `web_search` → `exec/web_search`

## Required environment

Set these in `~/.hermes/.env`:

```env
AMP_BACKEND_URL=http://127.0.0.1:5000
AMP_API_KEY=...
AMP_ORG_ID=O-0011-ST20251201090030
AMP_USERNAME=edwardgem@gmail.com
AMP_AGENT_NAME=my-hermes-agent-1028
```

Optional:

```env
AMP_HITL_TIMEOUT_MINUTES=10
AMP_HITL_POLL_INTERVAL_SECONDS=3
AMP_FAIL_CLOSED=true
```

`AGENT_NAME` is accepted as a fallback alias for `AMP_AGENT_NAME`.

## Local install for testing

```bash
ln -s /Users/edwardc/Projects/hermes ~/.hermes/plugins/amp-governance
hermes plugins enable amp-governance
hermes gateway restart
```

## Policy contract

This plugin expects the Hermes agent to have an AMP eval policy installed with
the normalized tool/action vocabulary above. The current baseline policy is:

- `/Users/edwardc/Projects/agents/O-0011-ST20251201090030/my-hermes-agent-1028/policy/policy_v1.json`
