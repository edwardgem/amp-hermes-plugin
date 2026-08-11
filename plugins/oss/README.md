# Governing Hermes through amp-community (OSS)

[`../saas/`](../saas/) governs Hermes tool calls through **AMP's SaaS
backend**. This directory shows the same governance pattern — intercept
a tool call, ask AMP for a decision, block or allow — against a
**self-hosted [`amp-community`](https://github.com/inquiryon/amp-community)**
instance instead.

There are two independent, complete example plugins here, and three
READMEs in total (this one, plus one per example). This page covers the
prerequisites both examples share and the final "try it" step both end
at; each example's own README covers only what's different about it
(install + configure). Read them in this order:

1. **This page** — prerequisites (steps 1–3 below).
2. **[`rest/README.md`](rest/README.md)** or **[`sdk-python/README.md`](sdk-python/README.md)**
   — pick one, install and configure it.
3. **Back to this page** — "Step 4: Try it", below.

| | [`rest/`](rest/) | [`sdk-python/`](sdk-python/) |
|---|---|---|
| Talks to | `amp-community`'s `/api/v0/...` REST API | same API, via [`amp-sdk-python`](https://github.com/inquiryon/amp-sdk-python) |
| Dependencies | none (stdlib `urllib`, matches the SaaS plugin's own style) | `inquiryon-amp-sdk` |
| Good for | any language reference, zero-dependency governance components | typed client, built-in retries/idempotency |

Both govern the same four representative Hermes tools (`terminal`,
`read_file`, `write_file`, `patch`) against the same policy. Pick
whichever matches how you'd rather build your own plugin — both are
equally supported patterns. Neither imports anything from `../../` or
talks to the SaaS backend at all.

## Step 1: Get amp-community running

Follow [`amp-community`'s own README](https://github.com/inquiryon/amp-community)
to get an instance running at `http://127.0.0.1:8080`. If you followed
its "Run the AMP Service" walkthrough already, it's the same instance —
you don't need a second one.

## Step 2: Know your tokens

Unlike AMP's SaaS backend, `amp-community` has **no "create an agent"
step** — no registration API, no agent registry. Being an agent here just
means holding a `service`-role Bearer token, defined statically in your
instance's `config.json`. If you used the example config as-is
(`examples/config.example.json` in `amp-community`), you already have:

| Role | Token | Used for |
|---|---|---|
| `reviewer` | `amp_k_test_CHANGE-ME-reviewer` | importing the policy below, approving/rejecting reviews |
| `service` | `amp_k_test_CHANGE-ME-agent` | what the Hermes plugin submits governed requests with |

**These are two different tokens for two different roles** — the most
common mistake at this step is using the `service` token to import the
policy, which fails with `403 forbidden: only reviewers manage policies`.
Policy import always needs the `reviewer` token; the plugin itself always
uses the `service` token.

## Step 3: Import the shared policy

Both examples govern against one policy, `hermes-oss-governance`. Its
formulas need embedded single quotes, which don't nest cleanly inside a
single-quoted curl body — write the JSON to a file first instead of
fighting shell quoting:

```bash
cat > /tmp/hermes-oss-governance.json <<'EOF'
{"action_governance": {"criteria": [
  {"criterion_id": "c-dangerous-command", "tool": "exec", "action": "exec", "hardness": "hard",
   "evaluator": {"type": "compute",
     "formula": "'rm -rf' in command or command.strip().startswith('sudo') or ('curl' in command and '| sh' in command)"}},
  {"criterion_id": "c-sensitive-write", "tool": "write", "action": "write", "hardness": "hard",
   "evaluator": {"type": "compute",
     "formula": "path.startswith('/etc') or path.startswith('/System') or '.env' in path or 'secret' in path.lower()"}},
  {"criterion_id": "c-sensitive-edit", "tool": "write", "action": "edit", "hardness": "hard",
   "evaluator": {"type": "compute",
     "formula": "path.startswith('/etc') or '.env' in path or 'secret' in path.lower()"}},
  {"criterion_id": "c-sensitive-read", "tool": "read", "action": "read", "hardness": "soft",
   "evaluator": {"type": "compute",
     "formula": "'.env' in path or 'secret' in path.lower() or path.startswith('/etc')"}}
]}}
EOF

curl -X PUT http://127.0.0.1:8080/api/v0/policies/hermes-oss-governance \
  -H "Authorization: Bearer amp_k_test_CHANGE-ME-reviewer" \
  -H "Content-Type: application/json" \
  -d @/tmp/hermes-oss-governance.json
```

Expect back `{"policy_id": "hermes-oss-governance", "stored": true}`. The
`/tmp` file is just a staging file for the curl body — `amp-community`
persists the policy itself into its own `policy_dir` automatically; you
don't need to move or keep the `/tmp` file afterward.

This policy demonstrates a realistic mix: hard-blocking dangerous shell
commands and writes/edits to sensitive paths (`/etc`, `.env`, anything
with "secret" in the name), plus a soft criterion that flags (without
blocking) reads of similarly sensitive paths.

**Now go install one of the two examples:** [`rest/README.md`](rest/README.md)
or [`sdk-python/README.md`](sdk-python/README.md). Come back here for
Step 4 once it's installed and configured.

## Step 4: Try it

With the plugin installed, configured, and Hermes restarted, try each of
these in your Hermes channel — each hits a different part of the policy:

1. **Safe write (approve this one)** — triggers `c-sensitive-write` (hard,
   pauses for review):
   > Create a file at /tmp/.env.test with the content FOO=bar

2. **Dangerous command (reject this one)** — triggers `c-dangerous-command`
   (hard). Reject rather than approve: if approved, Hermes will actually
   attempt a real `sudo` command on your machine and may hang waiting for
   your system password.
   > Run this terminal command: sudo rm -rf /tmp/nonexistent-test-file

3. **Soft-flagged read (no approval needed)** — triggers `c-sensitive-read`
   (soft: flagged, not blocked). This one goes through immediately —
   good contrast against the two hard criteria above.
   > Read the contents of .env

For each: after sending the prompt, open the AMP Community Edition
Operator UI at `http://127.0.0.1:8080/`:

- **Settings** tab → paste in the reviewer token
  (`amp_k_test_CHANGE-ME-reviewer`) → "Use token". Needed once per
  browser session before Worktray/policy actions will work.
- **Worktray** tab → the pending review appears here. Approve or reject
  it, and watch Hermes pick up the decision and continue (or stop).
- **Audit** tab → after all three prompts, query with no request id to
  see the full activity log — including the soft-flagged read that never
  paused anything.
