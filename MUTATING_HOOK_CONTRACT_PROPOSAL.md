# Mutating hook contract

**Status:** Reviewed by webdevtodayjason on `NousResearch/hermes-agent#64231`
(2026-08-01) — green-lit with one dispatch-wording correction, now landing as
`docs/plugins/hook-taxonomy.md` in a fork PR, alongside the `#64662`
(`LLMExecutionBlocked`) implementation.
**Covers:** `#64662` (`llm_execution` block signal), `#58524` (`classify_api_error`
first-valid-wins), and any future hook that lands in the same bucket.
**Author:** edwardgem, with input from webdevtodayjason (classify_api_error / #58524).

**Correction from review (2026-08-01):** Shape B is dispatched run-all, not
short-circuit — the runner calls every registered plugin, isolating each
one's failures, then picks the first valid result. It does not stop calling
later plugins once an earlier one answers. Renamed from "value short-circuit"
to "first-valid-wins" below to match. See the canonical version in
`docs/plugins/hook-taxonomy.md` for the final wording; this file is now a
historical record of the original design-pass draft.

---

## Scope

This covers hooks in the **mutating** bucket — callbacks that return a value or raise a
signal that changes control flow, as opposed to observer hooks that are only notified
after the fact. Based on the two confirmed members of the bucket (#64662, #58524) and
the requirements @webdevtodayjason raised in-thread.

## Two shapes, one bucket

Mutating hooks split into two patterns depending on what "mutating" means at that call site.

### A. Block signal — used by #64662 (`llm_execution`)

A hook needs to unconditionally stop an operation from proceeding. Raising a plain
`Exception` doesn't work here: the middleware runner's `except Exception` fallthrough
handler catches it and falls through to the next middleware (or the terminal call),
silently defeating the block. Fix: a purpose-built exception subclass, with an explicit
`except <Name>: raise` in the runner positioned *before* the generic fallthrough.

```python
class LLMExecutionBlocked(Exception):
    """
    Raised by llm_execution middleware to unconditionally prevent an LLM API call.

    The middleware runner explicitly re-raises this exception before the general
    ``except Exception`` fallthrough handler, so raising it from any middleware
    callback in the chain reliably propagates to the caller.
    """
    def __init__(self, reason: str, *, metadata: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.metadata = metadata or {}
```

Runner change — one new clause, before the existing general handler:

```python
except LLMExecutionBlocked:      # NEW — explicit re-raise before fallthrough
    raise
except _DownstreamExecutionError as exc:
    raise exc.original
except Exception as exc:
    ...  # existing fallthrough, unchanged
```

`Exception`, not `BaseException`: using `BaseException` would conflate a domain signal
with true interpreter-level events (`SystemExit`, `KeyboardInterrupt`). The explicit
`except LLMExecutionBlocked: raise` line is also self-documenting — it states, at the
point a reviewer is reading the runner, "this must not be swallowed by the fallthrough
path."

Usage:

```python
def my_middleware(request, next_call, session_id, **ctx):
    if budget_exceeded(session_id):
        raise LLMExecutionBlocked(
            "Session cost budget exceeded",
            metadata={"budget_usd": 5.0, "session_id": session_id},
        )
    return next_call(request)
```

### B. Value short-circuit — used by #58524 (`classify_api_error`)

A hook needs to supply an answer that may or may not be given, and the first plugin to
answer wins over the built-in pipeline. Contract:

- Callback returns `None` to decline (defer to the next plugin, then the built-in
  pipeline), or a non-`None` classification to answer.
- The runner stops at the **first non-`None` return**; later plugins in the chain are
  not called for that dispatch.
- If two plugins are both capable of answering, only the first-registered one is ever
  asked. Registration order is the tie-break — worth documenting explicitly at the
  registration point rather than leaving it implicit, since two silent-until-conflict
  plugins is exactly how #64714's "first-wins transform semantics" issue happened.

## Cross-cutting conventions (apply to both shapes)

1. **Keyword-only payload.** Every mutating hook callback takes keyword-only arguments,
   no positional payload. Matches `classify_api_error`'s existing signature; costs
   nothing to formalize.

2. **Privacy gate.** Any payload field that may carry raw user content or an unredacted
   provider dump (`error_body`, `error_message`, prompt/message text, etc.) gets called
   out explicitly in the hook's docstring with a `Privacy:` line. This doesn't try to
   enforce redaction in the runner — it makes the exposure visible and documented at the
   point a reviewer or auditor needs it, which is the actual ask from the #58248 class of
   issue.

3. **Hot-path signaling.** Each hook declares whether it fires on every call (hot) or
   only on a bounded trigger (cold). This varies *within* the bucket — `llm_execution`
   is hot (fires on every LLM call), `classify_api_error` is cold (fires only on API
   failure) — so it can't be inferred from "mutating" alone and needs to be explicit.
   Proposal: a `HOT_PATH: bool` class attribute or docstring field, giving
   @kshitijk4poor's proposed CI check (flag a new hook missing a cost guard) something
   machine-checkable to key off.

4. **Schema versioning.** Deferred to #64179 — this draft doesn't block on it. Once that
   lands, both hooks in this bucket adopt whatever field-versioning convention it defines.

## Applying it to the two known members

| | `#64662` `llm_execution` | `#58524` `classify_api_error` |
|---|---|---|
| Shape | A — block signal | B — value short-circuit |
| Payload | keyword-only, already | keyword-only, already |
| Privacy-flagged fields | request/prompt content | `error_body`, `error_message` |
| Hot/cold | **hot** — every LLM call | **cold** — API-failure-triggered only |

## Open questions for the group

- **Shared base class or per-site subclass for shape A?** `LLMExecutionBlocked` is
  purpose-named for its call site, matching the existing `_DownstreamExecutionError`
  naming precedent. Open to a shared `MiddlewareBlocked` base if the group prefers a
  common catch point, with per-site subclasses under it.
- **Tie-break for shape B beyond registration order?** Defaulting to registration order
  for now — a priority mechanism is easy to add later and hard to remove once plugins
  depend on it.
- **Does this bucket want a name in the `<subsystem>_<noun>_<verb-past>` grammar**, or
  does "mutating hook" stay a cross-cutting category above that grammar?

Once the shape here is confirmed, I'll turn this into `docs/plugins/hook-taxonomy.md`
(per @kshitijk4poor's suggestion above) and open the `#64662` PR — already scoped at
roughly 250 lines across `hermes_cli/middleware.py`, `agent/conversation_loop.py`, and
a new test file, fully backward-compatible with no changes to existing middleware.
Glad to also take a pass at conforming `#58524` to the same doc once @webdevtodayjason
gives it a look.
