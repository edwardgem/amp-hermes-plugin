# Governing Hermes through amp-community (OSS)

The plugin at the repo root (`../../`) governs Hermes tool calls through
**AMP's SaaS backend**. These two examples show the same governance
pattern — intercept a tool call, ask AMP for a decision, block or allow —
against a **self-hosted [`amp-community`](https://github.com/inquiryon/amp-community)**
instance instead. They are independent, complete, standalone plugins, not
an extension of the root plugin: neither imports anything from `../../`,
and neither talks to the SaaS backend at all.

Both examples govern the same four representative Hermes tools
(`terminal`, `read_file`, `write_file`, `patch`) against the same policy,
and differ only in how the Python code talks to amp-community's REST API:

| | `rest/` | `sdk-python/` |
|---|---|---|
| Talks to | `amp-community`'s `/api/v0/...` REST API | same API, via [`amp-sdk-python`](https://github.com/inquiryon/amp-sdk-python) |
| Dependencies | none (stdlib `urllib`, matches the root plugin's own style) | `inquiryon-amp-sdk` |
| Good for | any language reference, zero-dependency governance components | typed client, built-in retries/idempotency |

Pick whichever matches how you'd rather build your own plugin — both are
equally supported patterns.

## Prerequisites (shared by both examples)

1. A running `amp-community` instance. Follow its own
   [README](https://github.com/inquiryon/amp-community) to get one up on
   `http://127.0.0.1:8080`.
2. A `service`-role token from that instance's `config.json` (the same
   kind of token used as `amp_k_test_CHANGE-ME-agent` in amp-community's
   own walkthrough).
3. Import the policy both examples govern against. The formulas below
   need embedded single quotes, which don't nest cleanly inside a
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
     -H "Authorization: Bearer <your-reviewer-token>" \
     -H "Content-Type: application/json" \
     -d @/tmp/hermes-oss-governance.json
   ```

   This policy demonstrates a realistic mix: hard-blocking dangerous
   shell commands and writes/edits to sensitive paths (`/etc`, `.env`,
   anything with "secret" in the name), plus a soft criterion that flags
   (without blocking) reads of similarly sensitive paths.

Then continue into whichever example directory you want to try.
