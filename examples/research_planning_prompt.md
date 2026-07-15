<!--
Phase 3B reference material — NOT loaded by AHP today.

A future research-agent skill would render this template with the contents of
research_topics.yaml and pass it to an LLM to produce the structured plan dict
that gets submitted to AHP's evaluate_proposed_plan(session_id, plan). AHP does
not call an LLM, load this file, or otherwise know this prompt exists — it only
consumes the resulting plan dict. This template is intentionally model-neutral
(no provider-specific instructions or formatting).
-->

# Research Execution Planning

You are planning a research execution run, not performing the research itself.
Given a list of topics and research parameters, produce a structured cost and
scope estimate for the run — you will not search for anything or write a report
in this step.

## Inputs

- Topics: {{topics}}
- Research depth: {{research_depth}}
- Sources per topic: {{sources_per_topic}}
- Lookback window (days): {{lookback_days}}

## What to estimate

For the full run across all topics, estimate:

- A one- or two-sentence summary of what the run will do
- Projected total cost in USD across all LLM calls this run will make
- How confident that cost estimate is: "estimated" (default), "actual" (only if
  you have real pricing data), or "unknown" (if you cannot estimate at all)
- Total number of LLM calls the run will make (research + synthesis per topic)
- Total number of tool calls the run will make (e.g. web searches, one or more
  per source per topic)
- Total wall-clock duration in minutes
- Total number of discrete work units (typically one per topic)

Be conservative — round up rather than under-estimate, since this estimate is
what a human reviewer uses to decide whether to approve the run's budget.

## Output format

Respond with a single JSON object and nothing else:

```json
{
  "summary": "<one or two sentences>",
  "plan_type": "research",

  "projected_cost_usd": <number>,
  "projected_cost_status": "estimated",

  "estimated_llm_calls": <integer>,
  "estimated_tool_calls": <integer>,
  "estimated_duration_minutes": <integer>,

  "work_units_total": <integer>,

  "payload": {
    "topics": [<the input topics>],
    "research_depth": "<the input research_depth>",
    "sources_per_topic": <the input sources_per_topic>
  }
}
```

`plan_type` is always `"research"` for this planner. `payload` is passed
through untouched by AHP — put anything the execution step (Phase 3B, not yet
implemented) will need there.
