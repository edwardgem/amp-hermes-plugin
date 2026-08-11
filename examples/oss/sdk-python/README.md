# amp-oss-sdk-example

Governs Hermes tool calls through `amp-community`'s self-hosted OSS API
using the [`amp-sdk-python`](https://github.com/inquiryon/amp-sdk-python)
typed client. Same policy and governance logic as `../rest/` — only the
client differs. See `../README.md` first for prerequisites (a running
`amp-community` instance and the shared policy).

## Install as a Hermes plugin

```bash
cp -r examples/oss/sdk-python ~/.hermes/plugins/amp-oss-sdk-example
```

Add it to `~/.hermes/config.yaml`'s `plugins.enabled` list:

```yaml
plugins:
  enabled:
    - amp-oss-sdk-example
```

(If you already have `amp-governance` enabled for SaaS, either list both,
or swap one out temporarily — they don't conflict, but running both at
once double-governs every tool call.)

## Install the SDK — into Hermes's own venv

Unlike `../rest/`, this example depends on `amp-sdk-python`, which isn't
published to PyPI yet — install it from a local clone. Hermes runs in its
own dedicated virtualenv (not your system Python), so install into
*that* interpreter, not whichever `python`/`pip` your shell defaults to:

```bash
~/.hermes/hermes-agent/venv/bin/pip install -e /path/to/amp-sdk-python
```

(If your Hermes installation puts its venv somewhere else, adjust the
path — check `head -5 $(which hermes)` to see where it actually points.)

## Configure

Add to `~/.hermes/.env`:

```bash
AMP_OSS_BASE_URL=http://127.0.0.1:8080
AMP_OSS_AGENT_TOKEN=<your-service-token>
AMP_OSS_POLICY_ID=hermes-oss-governance
```

`AMP_OSS_POLICY_ID` defaults to `hermes-oss-governance` if unset, matching
the policy id used in `../README.md`'s prerequisites. Optional:
`AMP_OSS_HITL_TIMEOUT_MINUTES` (default `10`),
`AMP_OSS_HITL_POLL_INTERVAL_SECONDS` (default `3`),
`AMP_OSS_FAIL_CLOSED` (default `true` — block, not allow, when AMP is
unreachable or unconfigured).

Restart Hermes to pick up the new plugin and env vars.

## Try it

Same as `../rest/`: ask Hermes to run a command matching one of the
governed criteria (a `terminal` call containing `sudo`, a `write_file`
call targeting a path containing `.env`, etc.). The tool call pauses;
approve or reject it from `amp-community`'s Operator UI worktray
(`http://127.0.0.1:8080/`) or via `curl POST /api/v0/hitl/{id}/resolve`
as documented in `amp-community`'s own README.
