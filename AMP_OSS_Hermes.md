# Hermes Agent Governance With Inquiryon AMP — OSS Edition

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

You're here because you're connecting Hermes to a **self-hosted
`amp-community`** instance. If you meant to use **AMP SaaS** instead, go
back to [`README.md`](README.md) and follow the SaaS branch — see
[`AMP_SaaS_Hermes.md`](AMP_SaaS_Hermes.md).

Self-hosted `amp-community` works differently from SaaS in one important
way: there's **no "create an agent" step** — no registration API, no
agent registry. Being an agent just means holding a `service`-role
Bearer token, defined statically in your `amp-community` instance's
`config.json`. A separate `reviewer`-role token handles policy
management and approvals — these are two different tokens for two
different jobs, and mixing them up (e.g. using the service token to
import a policy) is the most common setup mistake.

Full setup — getting `amp-community` running, understanding both tokens,
importing a policy, and two complete, ready-to-run example plugins (one
using raw REST calls, one using the `amp-sdk-python` typed client) —
lives in **[`examples/oss/README.md`](examples/oss/README.md)**.
Continue there.
