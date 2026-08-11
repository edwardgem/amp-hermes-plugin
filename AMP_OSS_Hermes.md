# Hermes Agent Governance With Inquiryon AMP — OSS Edition

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

You're here because you're connecting Hermes to a **self-hosted
`amp-community`** instance. If you meant to use **AMP SaaS** instead, go
back to [`README.md`](README.md) and follow the SaaS branch — see
[`AMP_SaaS_Hermes.md`](AMP_SaaS_Hermes.md).

Self-hosted `amp-community` works differently from SaaS in one important
way: there's **no "create an agent" step** — no registration API, no
agent registry. Instead, everything runs on two Bearer tokens, defined
statically in your `amp-community` instance's `config.json`:

- **`service`-role token** — what your Hermes agent uses to submit
  governed requests. This is "being an agent" in OSS.
- **`reviewer`-role token** — handles policy management and approving/
  rejecting reviews.

These are two different tokens for two different jobs, and mixing them
up (e.g. using the service token to import a policy) is the most common
setup mistake.

Don't have `amp-community` set up yet? Go to the
[`amp-community`](https://github.com/inquiryon/amp-community) repo and
follow its README to get an instance running.

Once it's up and running, follow
**[`examples/oss/README.md`](examples/oss/README.md)** to import the
shared policy and pick one of the two ready-to-run example plugins (one
using raw REST calls, one using the `amp-sdk-python` typed client).
Continue there.
