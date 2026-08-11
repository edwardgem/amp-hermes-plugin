# amp-oss-rest-example

Governs Hermes tool calls through `amp-community`'s self-hosted OSS REST
API using raw `urllib` — no third-party dependency, same convention as
this repo's own `amp_client.py`. See `../README.md` first for
prerequisites (a running `amp-community` instance and the shared policy),
and `../sdk-python/` for the same logic built on `amp-sdk-python` instead.

## Install as a Hermes plugin

```bash
cp -r examples/oss/rest ~/.hermes/plugins/amp-oss-rest-example
```

Add it to `~/.hermes/config.yaml`'s `plugins.enabled` list:

```yaml
plugins:
  enabled:
    - amp-oss-rest-example
```

(If you already have `amp-governance` enabled for SaaS, either list both,
or swap one out temporarily — they don't conflict, but running both at
once double-governs every tool call.)

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

Ask Hermes to run a command matching one of the governed criteria — for
example, a `terminal` call containing `sudo`, or a `write_file` call
targeting a path containing `.env`. The tool call pauses; approve or
reject it from `amp-community`'s Operator UI worktray
(`http://127.0.0.1:8080/`) or via `curl POST /api/v0/hitl/{id}/resolve`
as documented in `amp-community`'s own README.
