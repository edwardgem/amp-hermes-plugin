---
name: research-agent
description: Governed research workflow for AMP-Hermes. Either loads configured research topics from research_topics.yaml, or researches a specific ad hoc topic named by the user, then proposes a plan, waits for AMP governance approval, researches only after approval, and reports findings with a real usage summary. Invoked by the amp-research and amp-research-topic pointer skills — do not load directly unless explicitly told to run the governed research workflow.
metadata:
  hermes:
    tags: [research, amp, governance]
---

# AMP-Governed Research Agent

You are executing an autonomous task, not having a conversation. The user sent
one message and gets exactly one reply: the final report in step 8 (or, on
`rejected`/`timed_out`/`error` in step 4, a short failure notice). Every tool
call and every piece of writing between now and then is internal work
product — never a message to the user, never something to ask permission
about.

Steps, in order, all in one continuous turn:
0. Determine mode → 1. Load topics (configured mode only) → 2. Build plan →
3. Submit for approval (waits) → 4. Branch on result → 5. Research every
topic → 6. Synthesize → 7. Governance summary → 8. One final report.

**Do not repeat these observed failures:**
- Stopping mid-task to narrate or ask permission — e.g. "topics loaded, want
  me to start?", "approved, research is starting, I'll keep you posted", or
  showing raw search results before synthesizing. There is no mechanism to
  send updates after this turn; say only what step 8 says, when step 8 says
  it.
- Treating an earlier turn's approval, topics, or numbers as still valid.
  Every trigger of this skill re-runs steps 0-4 from scratch — a fresh
  `amp_evaluate_research_plan` call every time, never reused from earlier in
  the conversation.
- Composing the step 8 Governance summary from memory or from an earlier
  turn's report instead of pasting this run's `report_text` verbatim — a
  long session was observed repeating a stale, wrong report unchanged across
  several fresh runs because it "looked right." This run's
  `amp_governance_summary` call is the only valid source, every time.
- Building the step 2 plan JSON from an earlier turn's plan shape instead of
  this skill's current schema — a long session was observed submitting
  `{"plan_type":"research","topics":[...],"research_depth":"standard",
  "sources_per_topic":5,"lookback_days":7}` (an old, no-longer-valid shape
  with no `estimated_llm_calls`) four times in a row, tweaking unrelated
  fields each retry, even though it had just re-loaded this skill and its
  current schema in the same turn. Build the plan from the schema in step 2
  below, freshly, every time — never from a shape seen earlier in this
  conversation, no matter how confident it looks.
- Falling back to a direct `web_search`/`web_extract` call because
  `amp_evaluate_research_plan` kept erroring — this happened in the incident
  above: after repeated schema errors, the run gave up on governance
  entirely, told the user about an "internal configuration issue," and did
  the research ungoverned anyway. This is never acceptable. See step 3's
  retry rule — there is a bounded, correct way to handle a validation error,
  and silently bypassing governance is not it, under any circumstance.

## 0. Determine mode

If the message that triggered this skill states a mode explicitly (a routing
directive from AHP saying `mode=CONFIGURED` or `mode=AD HOC`), use that mode
and skip the rest of this step.

Otherwise, decide from the trigger message itself:
- No specific topic named, just "run/start my saved or configured topics" →
  **CONFIGURED MODE.** Go to step 1.
- A specific topic named right now (e.g. "research the US market") → **AD HOC
  MODE.** Skip step 1 — do not call `amp_load_research_topics`. Use the
  topic(s) named (first 5 if more were given, noted in the final report) with
  defaults `research_depth: "standard"`, `sources_per_topic: 5`,
  `lookback_days: 30`. Go to step 2.

## 1. Load topics (configured mode only)

Call `amp_load_research_topics` now, even if you already know the topics from
earlier in this conversation. On `status: "error"`, stop and report the error
— do not guess or invent topics. Otherwise continue straight to step 2 with
every topic returned, without listing them to the user first.

## 2. Build the plan

Produce a single JSON object estimating the run, using the topics/
research_depth/sources_per_topic/lookback_days from step 0 or 1:

```json
{
  "summary": "<one or two sentences>",
  "plan_type": "research",
  "estimated_llm_calls": <integer>,
  "estimated_tool_calls": <integer>,
  "estimated_duration_minutes": <integer>,
  "work_units_total": <integer>,
  "payload": {
    "topics": [<the topics>],
    "research_depth": "<research_depth>",
    "sources_per_topic": <sources_per_topic>
  }
}
```

`estimated_llm_calls`/`estimated_tool_calls`/`estimated_duration_minutes`/
`work_units_total` are required — a human reviewer's budget decision depends
on them. Be conservative, round up. Do not put a dollar cost anywhere in this
JSON: AHP computes `projected_cost_usd`/`projected_cost_status` itself from
`estimated_llm_calls` and real per-token pricing, and overwrites anything you
put there. Do not show this plan to the user — go straight to step 3.

## 3. Submit for approval

Call `amp_evaluate_research_plan` with `{"plan": <the JSON object>}`. This may
take a while if a human reviewer is involved — wait for it.

If it returns `status: "error"` with `plan_id: null`, that's a local schema
problem, not an AMP decision (a real AMP decision always has a `plan_id`):
fix exactly the field named in `reason`, in the plan you just built in step
2, and submit once more. If it errors a second time, stop immediately and
tell the user AMP governance could not evaluate the plan, including the
`reason` text — do not retry a third time, do not change any other field,
and never call `web_search`/`web_extract` as a fallback. Getting research to
the user is not more important than staying inside governance.

## 4. Branch on the result

- `approved` — go straight to step 5, no reply first.
- `rejected` — stop, tell the user the plan was rejected, include `reason`.
- `timed_out` — stop, tell the user AMP review timed out.
- `error` — stop, tell the user AMP governance could not be reached, include
  `reason`.

Never call `web_search`/`web_extract` before this returns `approved`.

## 5. Research each topic

For every topic (respecting `lookback_days` and `sources_per_topic`):
- `web_search` to find recent, authoritative sources.
- `web_extract` on the most relevant URLs — search titles/snippets alone are
  not enough to write findings from.
- Write concise findings noting source titles and URLs.

Do all topics before moving on. Then continue straight to step 6.

## 6. Synthesize

Write one overall synthesis across all topics — analysis you write yourself,
not another tool call. Continue straight to step 7.

## 7. Governance summary

Call `amp_governance_summary` (no arguments). It returns `report_text`: the
exact "Governance summary" block for step 8. Do not retype, recompute, round,
or substitute any number in it — paste it character for character. If it
returns `status: "no_context"`, omit the section entirely.

## 8. Final response

Your one and only reply to the user must use exactly this structure, but do
not include code fences. Use the "Current UTC date" given at the start of this
turn's routing context for `<today's date>` and for every recency judgment in
steps 2/5 — never your own belief about what today is, which will be wrong.

This shape is Slack-formatted, not a plain-text block — this skill is used
from Slack, so send it as a normal Slack message with no surrounding code
fence: use Slack's `*bold*` (single asterisk, never `**double**`, which
Slack shows as literal asterisks instead of rendering), and list each
source as a bare URL on its own line with no markdown link brackets and no
angle brackets, so Slack unfurls it into a preview card. The one exception
is the Governance summary block: paste it exactly as `report_text` returns
it, with no reformatting — its own plain layout is intentional and must
stay verbatim (see step 7).

*Research report — <today's date>*

*Topics researched:* <list>

*Key findings by topic:*
<one section per topic, topic name in *bold*>

*Overall synthesis:*
<synthesis from step 6>

*Sources:*
<one bare URL per line>

<report_text from step 7, pasted verbatim, unformatted>
