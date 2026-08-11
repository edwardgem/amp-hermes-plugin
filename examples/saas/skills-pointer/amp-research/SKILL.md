---
name: amp-research
description: Use when the user asks to run, execute, or start their saved or configured research topics, with no specific topic named — e.g. "Run my research topics", "Run my daily research", "Research my configured topics". Do NOT use this if the user names a specific topic to research right now (e.g. "research the US market") — use amp-research-topic for that instead. Triggers the AMP-governed research workflow.
metadata:
  hermes:
    tags: [research, amp, governance, pointer]
---

# AMP Research (pointer)

This is a pointer skill. It exists only so this workflow is discoverable by name
and by natural language — the actual instructions live in the AMP governance
plugin's bundled `research-agent` skill.

Immediately call `skill_view(name="amp-governance:research-agent")` and follow
every instruction in the skill it returns, exactly, using the current session.
That skill's own step 0 determines configured vs ad hoc mode from the user's
message — do not assume or state a mode here. Do not attempt to load research
topics, build a plan, or research anything yourself from this file — that all
happens in the skill you load.
