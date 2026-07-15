# Hermes Upstream Proposal: LLM Execution Blocked Signal

**Author:** AMP-Hermes Plugin team  
**Date:** 2026-07-14  
**Target:** Hermes v0.16.x  
**Status:** Draft — awaiting product-owner approval before submission

---

## Summary

This document proposes a small, targeted change to Hermes' `llm_execution` middleware contract that would allow plugins to unconditionally prevent an LLM API call from proceeding.

---

## Background

Hermes supports `llm_execution` middleware that wraps the actual LLM provider call. A middleware callback receives `(request, next_call, ...)` and must call `next_call(request)` to proceed to the provider. This is the correct place for governance, safety, or rate-limiting plugins to observe and potentially intercept LLM calls.

However, the current middleware runner has a critical limitation: if middleware raises an `Exception` without calling `next_call`, the exception handler at `hermes_cli/middleware.py` catches it and falls through to the next middleware in the chain (or the terminal provider call). This means middleware **cannot block an LLM call by raising an `Exception`**.

The relevant code pattern in `hermes_cli/middleware.py`:

```python
try:
    return callback(**call_kwargs)
except _DownstreamExecutionError as exc:
    raise exc.original
except Exception as exc:
    logger.warning(...)
    if next_succeeded:
        return next_result
    if next_called:
        raise
    return call_at(index + 1, payload)   # ← falls through, bypassing block intent
```

---

## Problem

Governance and safety plugins need to be able to prevent an LLM call from proceeding. Current workarounds are all unsatisfactory:

| Approach | Problem |
|---|---|
| Raise `Exception` | Caught by middleware runner; falls through to provider |
| Set a mutable flag and check in a second middleware | Race-prone; requires coordinating two separate callbacks |
| Return a fake response without calling `next_call` | Caller receives garbage; undefined behavior |
| Modify Hermes for each plugin | Does not scale; creates a fork per governance plugin |

Without a supported block mechanism, plugins that need to enforce LLM-call governance (e.g., budget limits, safety filters, compliance checks) must either:
1. Skip `llm_execution` middleware entirely and rely on weaker `pre_tool_call`-level blocking
2. Maintain a fork of Hermes with their own ad hoc workaround

---

## Proposed Change

Add a named exception class that the middleware runner explicitly re-raises before the general `except Exception` fallthrough handler.

### File 1: `hermes_cli/middleware.py`

Add the following class (approximately 15 lines) at module level, and add one `except` clause inside `_run_execution_chain`:

```python
class LLMExecutionBlocked(Exception):
    """
    Raised by llm_execution middleware to unconditionally prevent an LLM API call.

    The middleware runner explicitly re-raises this exception before the general
    ``except Exception`` fallthrough handler, so raising it from any middleware
    callback in the chain reliably propagates to the caller of
    ``run_llm_execution_middleware``.

    Catch this at the ``run_llm_execution_middleware`` call site to provide an
    appropriate response to the user.

    Args:
        reason: Human-readable explanation for the block.
        metadata: Optional structured data passed to the caller.
    """

    def __init__(self, reason: str, *, metadata: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.metadata = metadata or {}
```

And in `_run_execution_chain`, add the explicit re-raise **before** the general fallthrough:

```python
try:
    return callback(**call_kwargs)
except LLMExecutionBlocked:      # ← NEW: re-raise before fallthrough
    raise
except _DownstreamExecutionError as exc:
    raise exc.original
except Exception as exc:
    logger.warning(...)
    if next_succeeded:
        return next_result
    if next_called:
        raise
    return call_at(index + 1, payload)
```

### File 2: `agent/conversation_loop.py`

Wrap the `run_llm_execution_middleware()` call (approximately 10 lines):

```python
from hermes_cli.middleware import (
    LLMExecutionBlocked,
    run_llm_execution_middleware,
)

try:
    response = run_llm_execution_middleware(
        api_kwargs, _perform_api_call, **middleware_context
    )
except LLMExecutionBlocked as _blocked:
    logger.info("LLM call blocked by middleware: %s", _blocked.reason)
    return {
        "final_response": f"This request was blocked before reaching the model: {_blocked.reason}",
        "messages": messages,
        "api_calls": api_call_count,
        "completed": False,
        "failed": True,
        "error": f"llm_execution_blocked: {_blocked.reason}",
    }
```

---

## Why `Exception` with explicit re-raise (not `BaseException`)

An earlier draft used `BaseException` as the base class, which would let `LLMExecutionBlocked` propagate through the `except Exception` fallthrough handler without any change to the runner itself. The final design uses `Exception` with an explicit `except LLMExecutionBlocked: raise` handler instead, for two reasons:

1. **`Exception` subclasses are the Python norm.** Using `BaseException` for a domain signal conflates it with true interpreter-level signals (`SystemExit`, `KeyboardInterrupt`, `GeneratorExit`). `LLMExecutionBlocked` is an intentional application-level block, not an OS signal or interpreter event.

2. **The explicit re-raise makes the intent visible.** The `except LLMExecutionBlocked: raise` line in the runner is a one-line self-documenting statement of intent: "this exception must not be swallowed by the fallthrough path." It is searchable, reviewable, and immediately clear to anyone reading the runner code.

**Why the explicit handler still works when `LLMExecutionBlocked` comes from downstream:**

If an inner middleware (or the terminal call) raises `LLMExecutionBlocked`, the `next_call()` closure wraps it as `_DownstreamExecutionError`. The outer handler `except _DownstreamExecutionError: raise exc.original` then re-raises `LLMExecutionBlocked` out of the `try/except` block, and it propagates to the caller of `call_at()`. The `except LLMExecutionBlocked: raise` handler at the outer middleware level catches it and re-raises it up the chain, so propagation is correct in all cases.

---

## Why This is Generic, Not AMP-Specific

This change enables a whole class of plugins that the current Hermes middleware system cannot support:

- **Budget enforcement plugins:** Block calls once a cost threshold is exceeded
- **Safety filters:** Block calls whose input context triggers a content policy
- **Rate-limiting plugins:** Block calls when per-minute or per-session token limits are hit
- **Compliance plugins:** Block calls during restricted hours or for restricted models

None of these require AMP. The `LLMExecutionBlocked` class has no AMP-specific fields or behavior. It is a generic, named signal with a `reason` string and an optional `metadata` dict.

---

## Implementation Size

| File | Lines changed |
|---|---|
| `hermes_cli/middleware.py` | +37 (new class + one except clause) |
| `agent/conversation_loop.py` | +18 (import + try/except block) |
| Test file (new) | ~160 lines |
| `AGENTS.md` (middleware plugin docs) | ~35 lines |

Total: approximately 250 lines across 4 files.

---

## Compatibility

- The change is fully backward-compatible. No existing middleware is affected.
- Existing code that does not raise `LLMExecutionBlocked` continues to work exactly as before.
- The explicit `except LLMExecutionBlocked: raise` in `_run_execution_chain` is a no-op for all existing middleware.

---

## Draft GitHub Issue

**Title:** `llm_execution` middleware cannot block LLM calls — `except Exception` fallthrough bypasses governance plugins

**Labels:** enhancement, middleware, governance

**Body:**

```
### Problem

Governance and safety plugins that register `llm_execution` middleware cannot prevent
an LLM API call from proceeding. If middleware raises an Exception without calling
next_call(), the exception handler in _run_execution_chain catches it and falls
through to the next middleware or the terminal provider call.

This makes it impossible to implement plugins that enforce:
- per-session token/cost budgets
- safety filters on input context  
- rate limiting
- compliance-based call restrictions

### Current behavior

Raising Exception in llm_execution middleware → caught by runner → provider called anyway.

### Requested behavior

A supported mechanism for middleware to signal "do not call the provider" in a way that
the middleware runner respects.

### Proposed solution

Add LLMExecutionBlocked(Exception) to hermes_cli/middleware.py and add an explicit
`except LLMExecutionBlocked: raise` handler in `_run_execution_chain` before the
general fallthrough path.

The conversation loop catches it at the run_llm_execution_middleware call site and
returns a user-visible blocked response.

This requires no changes to existing middleware contracts. Only middleware that
deliberately wants to block needs to raise LLMExecutionBlocked.

### Example use case

A governance plugin enforcing a per-session cost budget:

    from hermes_cli.middleware import LLMExecutionBlocked

    def llm_execution_middleware(request, next_call, session_id, model, ...):
        if cost_exceeded(session_id):
            raise LLMExecutionBlocked(
                "Session cost budget exceeded",
                metadata={"budget_usd": 5.0},
            )
        return next_call(request)

### Files affected

- hermes_cli/middleware.py — add LLMExecutionBlocked class + explicit re-raise (~37 lines)
- agent/conversation_loop.py — add except LLMExecutionBlocked handler (~18 lines)
```

---

## Draft Pull Request Description

**Title:** Add `LLMExecutionBlocked` to let middleware prevent LLM calls

**Body:**

```
## Problem

Plugins that register `llm_execution` middleware cannot block LLM calls.
When middleware raises an Exception without calling next_call(), the middleware runner
catches it and falls through to the terminal provider call (hermes_cli/middleware.py,
the `except Exception` handler in `_run_execution_chain`).

This prevents an entire class of valid plugin use cases: budget enforcement,
safety filters, content policy checks, rate limiting.

## Solution

Add `LLMExecutionBlocked(Exception)` to `hermes_cli/middleware.py`.

The runner is updated with an explicit `except LLMExecutionBlocked: raise` handler
positioned before the general fallthrough path, so the exception always propagates
to the caller regardless of which middleware in the chain raises it.

The conversation loop wraps `run_llm_execution_middleware()` with a new
`except LLMExecutionBlocked` handler that returns a synthetic "blocked" response,
giving the user a clear message.

## Changes

- `hermes_cli/middleware.py` — add `LLMExecutionBlocked(Exception)` class + re-raise
- `agent/conversation_loop.py` — wrap middleware call with `except LLMExecutionBlocked`
- `tests/hermes_cli/test_llm_execution_blocked.py` — 16 tests
- `AGENTS.md` — document llm_execution middleware blocking in the plugin guide

## Backward compatibility

Fully backward-compatible. No existing middleware is affected. Plugins that do
not raise `LLMExecutionBlocked` work exactly as before.

## Example

    from hermes_cli.middleware import LLMExecutionBlocked

    def my_middleware(request, next_call, session_id, **ctx):
        if budget_exceeded(session_id):
            raise LLMExecutionBlocked(
                "Cost budget exceeded",
                metadata={"budget_usd": 5.0, "session_id": session_id},
            )
        return next_call(request)

## Test plan

- [x] LLMExecutionBlocked class: reason attribute, metadata default/kwarg, catchable as Exception
- [x] Middleware raises directly without calling next_call → exception propagates, provider not called
- [x] Middleware calls next_call then raises → exception propagates (next_call result discarded)
- [x] Downstream raises LLMExecutionBlocked → propagates through outer pass-through middleware
- [x] 3-deep chain: block at first stops all downstream
- [x] Normal Exception without next_call still falls through (regression)
- [x] LLMExecutionBlocked not confused with plain Exception (regression)
- [x] No-callbacks fast path unaffected
- [x] metadata dict accessible on caught exception
```

---

## Recommended API

```python
# hermes_cli/middleware.py

class LLMExecutionBlocked(Exception):
    """
    Raised by llm_execution middleware to unconditionally prevent an LLM API call.

    The middleware runner explicitly re-raises this exception before the general
    ``except Exception`` fallthrough handler, so raising it from any middleware
    callback in the chain reliably propagates to the caller of
    ``run_llm_execution_middleware``.

    Args:
        reason: Human-readable explanation for the block.
        metadata: Optional structured data passed to the caller.

    Example::

        from hermes_cli.middleware import LLMExecutionBlocked

        def my_middleware(request, next_call, session_id, **ctx):
            if budget_exceeded(session_id):
                raise LLMExecutionBlocked(
                    "Session budget exceeded",
                    metadata={"budget_usd": 5.0, "session_id": session_id},
                )
            return next_call(request)
    """

    def __init__(self, reason: str, *, metadata: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.metadata = metadata or {}
```

### Why `LLMExecutionBlocked` rather than `GovernanceBlock` or `LLMExecutionBlock`

The name `LLMExecutionBlocked` is preferred over earlier working names because:

1. **Past tense matches Python conventions for error/signal names** (`BlockingIOError`, `TimeoutError`, `BufferError`) — the name describes a state, not an action
2. It describes *what is blocked* (an LLM execution) without implying a specific use case like governance
3. It matches the naming convention of `_DownstreamExecutionError` already in `hermes_cli/middleware.py`
4. It avoids implying that only governance plugins should use it (safety, rate-limiting, and compliance plugins are equally valid users)

---

## Next Steps

1. Get product-owner approval to open the GitHub Issue
2. Open the issue on the Hermes repository
3. Open the Pull Request linking to this document as background
4. Once merged, update AHP's Phase 2B implementation to use `LLMExecutionBlocked`
