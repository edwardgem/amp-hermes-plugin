# amp-oss-sdk-example

Governs Hermes tool calls through `amp-community`'s self-hosted OSS API
using the [`amp-sdk-python`](https://github.com/inquiryon/amp-sdk-python)
typed client. Same policy and governance logic as
[`../rest/`](../rest/) — only the client differs.

**Start at [`../README.md`](../README.md) first** if you haven't already
— it covers the prerequisites (getting `amp-community` running, your
tokens, importing the shared policy) that this page assumes are done.
Once you're finished here, continue to `../README.md`'s **"Step 4: Try
it"** to see it in action. (Looking for the zero-dependency raw-REST
version instead? See [`../rest/README.md`](../rest/README.md).)

## Step 1: Install as a Hermes plugin

Copy this directory into your Hermes plugins folder:

```bash
cp -r examples/oss/sdk-python ~/.hermes/plugins/amp-oss-sdk-example
```

Then add `amp-oss-sdk-example` to the `plugins.enabled` list in
`~/.hermes/config.yaml`. Paste this block in (or hand it to your AI
coding agent to apply):

```yaml
plugins:
  enabled:
    - amp-oss-sdk-example
```

If `plugins.enabled` already exists with other entries, add
`amp-oss-sdk-example` as a new list item instead of replacing the block
— don't remove plugins you already have there unless you mean to.

## Step 2: Install the SDK — into Hermes's own venv

Unlike `../rest/`, this example depends on `amp-sdk-python`, which isn't
published to PyPI yet — install it from a local clone. Hermes runs in its
own dedicated virtualenv (not your system Python), so install into
*that* interpreter, not whichever `python`/`pip` your shell defaults to:

```bash
~/.hermes/hermes-agent/venv/bin/pip install -e /path/to/amp-sdk-python
```

If your Hermes installation puts its venv somewhere else, adjust the
path — `head -5 $(which hermes)` shows where it actually points.

## Step 3: Configure

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

## Step 4: Restart Hermes

Restart Hermes to pick up the new plugin, the newly-installed SDK, and
the env vars.

**Done — continue to [`../README.md`](../README.md)'s "Step 4: Try it"**
for example prompts and how to approve/reject/inspect them.
