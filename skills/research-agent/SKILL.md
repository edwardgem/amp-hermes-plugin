---
name: research-agent
description: Governed research workflow for AMP-Hermes. Loads configured research topics, proposes a plan, waits for AMP governance approval, researches only after approval, and reports findings with a real usage summary. Invoked by the amp-research pointer skill — do not load directly unless explicitly told to run the governed research workflow.
metadata:
  hermes:
    tags: [research, amp, governance]
---

# AMP-Governed Research Agent

**You are executing an autonomous 8-step task, not having a conversation.** Nobody is watching you work step by step — the user sent one message and is waiting for exactly one reply: the final report in step 8 (or, on `rejected`/`timed_out`/`error` in step 4, a short failure notice). Between now and then, every tool call and every piece of writing (plan JSON, per-topic findings, synthesis) is internal work product, not something to show the user or ask permission about. If you find yourself about to write a sentence addressed to the user before step 8 is reached, stop — that sentence should not exist yet.

Checklist (do all of this in one continuous turn):
1. Load topics (tool call) → 2. Build plan (write JSON) → 3. Submit for approval (tool call, waits) → 4. Branch: approved→continue, anything else→stop and report → 5. Research every topic (search + extract, all topics) → 6. Write synthesis → 7. Get governance summary (tool call) → 8. Send the one final report.

**Three concrete mistakes from earlier runs of this exact skill — do not repeat any of them:**
- WRONG: after step 1, replying *"Your research topics have been successfully loaded... Would you like me to start the research now?"* — this is asking permission for something you were already told to do. Never do this.
- WRONG: after step 5, replying with a per-topic list of search result titles/snippets and *"Let me know if you want... analysis and synthesis of this information"* — search results are raw material, not the deliverable, and synthesis is not optional follow-up work, it is step 6 of this same turn.
- WRONG: seeing "run my research topics" again later in a conversation where you already loaded topics or got a plan approved earlier, and calling `web_search` directly because you already know the topics — **a prior approval earlier in this conversation does not apply to a new request.** Every time this workflow is triggered, run steps 1-4 again from scratch, including a fresh `amp_load_research_topics` call and a fresh `amp_evaluate_research_plan` call, even if you're confident you already know the topics or that a similar plan was approved before. AMP has no record of "already approved this session" — only of the specific plan you actually submit this time. Never call `web_search` or `web_extract` in response to this trigger without a fresh `status: "approved"` from `amp_evaluate_research_plan` in *this* invocation.

Follow the numbered steps below **in order**, do not skip or reorder them — the whole point of this workflow is that AMP approves the plan before any research spending happens, and that the user gets one complete report, not a running commentary.

## 1. Load topics

Call the `amp_load_research_topics` tool now, even if you already know the topics from earlier in this conversation — do not skip this call based on memory. No arguments are needed unless the user gave you a specific config path. If it returns `status: "error"`, stop and report the error to the user — do not guess topics or invent a config. Otherwise, continue immediately to step 2 — do not reply to the user with the loaded topics first.

## 2. Build the plan

Read `~/.hermes/plugins/amp-governance/examples/research_planning_prompt.md` with `read_file` and follow it exactly to produce the structured plan JSON, using the topics/research_depth/sources_per_topic/lookback_days you just loaded as the inputs it asks for. Be conservative in your cost/call/duration estimates — round up, don't under-estimate. Do not show the plan to the user or ask them to confirm it — continue immediately to step 3. AMP's own approval step is the review checkpoint, not a reply from you.

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
- Use `web_extract` on the *most relevant* URLs to actually pull page content — do not stop at search result titles/snippets, those are not enough to write real findings from.
- Write concise findings for that topic based on the extracted content, noting source titles and URLs.

Do this for all topics before moving on — do not reply to the user with topic results as you go. You do not need to track cost or call counts yourself — AMP governance observes every LLM and tool call automatically in the background. Once every topic has findings, continue immediately to step 6 in the same turn.

## 6. Synthesize

Write one overall synthesis across all topics, not just a list of per-topic notes. This is analysis you write yourself from the findings above, not another tool call. Continue immediately to step 7 in the same turn — do not present the synthesis to the user yet.

## 7. Governance summary

Call `amp_governance_summary` (no arguments). Use only the fields it returns for the summary — if it returns `status: "no_context"`, or a field you need isn't present in the response, omit that line rather than inventing a number. Continue immediately to step 8 in the same turn.

## 8. Final response

Before writing anything: have you already sent the user any message since this task started? You should not have — if you have, that was a mistake in an earlier step. This is the first and only reply you send the user for a successful run. It must include all five sections below, fully populated, in one message — not a partial list of search results, not "here's what I found so far." Reply with:

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
