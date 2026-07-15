---
name: amp-research
description: Use when the user asks to run, execute, or start their configured research topics — e.g. "Run my research topics", "Run my daily research", "Research my configured topics". Triggers the AMP-governed research workflow.
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
Do not attempt to load research topics, build a plan, or research anything
yourself from this file — that all happens in the skill you load.
