---
name: research-agent
description: Governed research workflow for AMP-Hermes. Loads configured research topics, proposes a plan, waits for AMP governance approval, researches only after approval, and reports findings with a real usage summary. Invoked by the amp-research pointer skill — do not load directly unless explicitly told to run the governed research workflow.
metadata:
  hermes:
    tags: [research, amp, governance]
---

# AMP-Governed Research Agent

You are running one governed research pass. Follow these steps **in order** and do not skip or reorder them — the whole point of this workflow is that AMP approves the plan before any research spending happens.

## 1. Load topics

Call the `amp_load_research_topics` tool (no arguments needed unless the user gave you a specific config path). If it returns `status: "error"`, stop and report the error to the user — do not guess topics or invent a config.

## 2. Build the plan

Read `~/.hermes/plugins/amp-governance/examples/research_planning_prompt.md` with `read_file` and follow it exactly to produce the structured plan JSON, using the topics/research_depth/sources_per_topic/lookback_days you just loaded as the inputs it asks for. Be conservative in your cost/call/duration estimates — round up, don't under-estimate.

## 3. Submit for approval

Call `amp_evaluate_research_plan` with `{"plan": <the JSON object from step 2>}`. This call may take a while if a human reviewer needs to approve it in AMP — that's expected, wait for it.

## 4. Branch on the result

- `status: "approved"` — proceed to step 5.
- `status: "rejected"` — stop. Tell the user the plan was rejected and include the `reason` field. Do not research anything.
- `status: "timed_out"` — stop. Tell the user AMP review timed out. Do not research anything.
- `status: "error"` — stop. Tell the user AMP governance could not be reached and include the `reason` field. Do not research anything.

**Do not call `web_search` or `web_extract` before this step returns `status: "approved"`.**

## 5. Research each topic

For each topic (respecting `lookback_days` for recency and `sources_per_topic` for how many sources to gather per topic):
- Use `web_search` to find sources, preferring recent and authoritative results.
- Use `web_extract` on the most relevant URLs to pull content.
- Write concise findings for that topic, noting source titles and URLs.

You do not need to track cost or call counts yourself — AMP governance observes every LLM and tool call automatically in the background.

## 6. Synthesize

Write one overall synthesis across all topics, not just a list of per-topic notes.

## 7. Governance summary

Call `amp_governance_summary` (no arguments). Use only the fields it returns for the summary — if it returns `status: "no_context"`, or a field you need isn't present in the response, omit that line rather than inventing a number.

## 8. Final response

Reply with:

```text
Research report — <today's date>

Topics researched: <list>

Key findings by topic:
<one section per topic>

Overall synthesis:
<synthesis from step 6>

Sources:
<titles + URLs>

Governance summary
Plan projected cost: $<plan's projected_cost_usd>
Approved budget: $<approved_budget_usd from the plan-approval result>
Actual cost: $<total_cost_usd from amp_governance_summary>
LLM calls: <llm_calls from amp_governance_summary>
Tool calls: <tool_calls from amp_governance_summary>
AMP plan approvals: 1
Runtime HITL approvals: <llm_hitl_approved from amp_governance_summary>
```

This is your normal turn response — no special formatting or tool call is needed to "return" it.
