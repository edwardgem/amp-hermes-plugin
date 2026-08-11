---
name: amp-research-topic
description: Use when the user asks to research a specific topic right now — e.g. "research the US market", "look into X for me", "run research on Y" — as opposed to running their saved or configured research topics. Do NOT use this if the user just says something like "run my research topics" with no specific topic named — use amp-research for that instead. Triggers the same AMP-governed research workflow in ad hoc mode.
metadata:
  hermes:
    tags: [research, amp, governance, pointer]
---

# AMP Research — ad hoc topic (pointer)

This is a pointer skill. It exists only so ad hoc, one-off research requests are
discoverable by natural language — the actual instructions live in the AMP
governance plugin's bundled `research-agent` skill, same as the configured-topics
pointer.

Immediately call `skill_view(name="amp-governance:research-agent")` and follow
every instruction in the skill it returns, exactly, using the current session.
That skill's own step 0 determines configured vs ad hoc mode from the user's
message — do not assume or state a mode here. Do not attempt to load research
topics, build a plan, or research anything yourself from this file — that all
happens in the skill you load.
