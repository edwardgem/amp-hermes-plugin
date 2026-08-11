# amp-oss-rest-example

Governs Hermes tool calls through `amp-community`'s self-hosted OSS REST
API using raw `urllib` — no third-party dependency, same convention as
this repo's own `amp_client.py`.

**Start at [`../README.md`](../README.md) first** if you haven't already
— it covers the prerequisites (getting `amp-community` running, your
tokens, importing the shared policy) that this page assumes are done.
Once you're finished here, continue to `../README.md`'s **"Step 4: Try
it"** to see it in action. (Looking for the SDK-based version instead of
raw REST? See [`../sdk-python/README.md`](../sdk-python/README.md).)

## Step 1: Install as a Hermes plugin

Copy this directory into your Hermes plugins folder:

```bash
cp -r plugins/oss/rest ~/.hermes/plugins/amp-oss-rest-example
```

Then add `amp-oss-rest-example` to the `plugins.enabled` list in
`~/.hermes/config.yaml`. Paste this block in (or hand it to your AI
coding agent to apply):

```yaml
plugins:
  enabled:
    - amp-oss-rest-example
```

If `plugins.enabled` already exists with other entries, add
`amp-oss-rest-example` as a new list item instead of replacing the block
— don't remove plugins you already have there unless you mean to.

## Step 2: Configure

Add these lines to `~/.hermes/.env`:

```bash
AMP_OSS_BASE_URL=http://127.0.0.1:8080
AMP_OSS_AGENT_TOKEN=amp_k_test_CHANGE-ME-agent
AMP_OSS_POLICY_ID=hermes-oss-governance
```

The values above match `amp-community`'s example config exactly — if you
followed its README as-is, you can paste this block unmodified.
`AMP_OSS_AGENT_TOKEN` must be the **`service`**-role token (not the
`reviewer` token — see `../README.md`'s "Step 2: Know your tokens" for
why that distinction matters).

`AMP_OSS_POLICY_ID` defaults to `hermes-oss-governance` even if you omit
this line, matching the policy id from `../README.md`'s Step 3. Optional,
all with sensible defaults if omitted:

| Variable | Default | Meaning |
|---|---|---|
| `AMP_OSS_HITL_TIMEOUT_MINUTES` | `10` | how long to wait for a reviewer before blocking |
| `AMP_OSS_HITL_POLL_INTERVAL_SECONDS` | `3` | how often to check for a decision while waiting |
| `AMP_OSS_FAIL_CLOSED` | `true` | block (not allow) when AMP is unreachable or unconfigured |

## Step 3: Restart Hermes

Restart Hermes to pick up the new plugin and env vars.

**Done — continue to [`../README.md`](../README.md)'s "Step 4: Try it"**
for example prompts and how to approve/reject/inspect them.
