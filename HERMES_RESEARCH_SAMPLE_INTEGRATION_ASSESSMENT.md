# Phase 3B Integration Assessment: Research-Agent Skill

**Date:** 2026-07-15
**Status:** Research only — no Phase 3B code in this cycle
**Scope:** How a future research-agent skill would trigger from a chat message, read local config, call an LLM for planning, hand the plan to AHP's `evaluate_proposed_plan()` (Phase 3A, this repo), and be schedulable via cron
**Method:** Source-code inspection of `~/.hermes/hermes-agent/` (the installed Hermes checkout AHP runs against) and `~/.hermes/skills/`, with file/line citations for every claim

---

## Correction to an earlier assumption

Phase 3A design work (this repo's `AMP_HERMES_RESOURCE_GOVERNANCE_ASSESSMENT.md`) assumed the plugin hook system's `VALID_HOOKS` set was the only extension surface available to AHP — i.e. that a plugin can only observe/block Hermes' own built-in tool and LLM calls, not register anything new that a skill could call. **This is incorrect.** `hermes_cli/plugins.py`'s `PluginContext` exposes a separate, first-class API — `register_tool()`, `register_skill()`, `register_command()`, `ctx.llm` — that is architecturally independent of `VALID_HOOKS`. AHP currently uses none of it (it registers only hooks and, conditionally, the `llm_execution` middleware). This changes the Phase 3B picture: the research-agent skill does not need an indirect mechanism to reach `evaluate_proposed_plan()` — AHP can register it as a normal tool the skill's LLM turn calls directly.

## 1. How Hermes defines a custom skill

A skill is a single `SKILL.md` file — pure Markdown, no executable code. There is no separate "system prompt" field; the skill body *is* the instructions injected into the conversation when loaded.

- **Required frontmatter** (`~/.hermes/skills/software-development/hermes-agent-skill-authoring/SKILL.md:29-56`, enforced by `tools/skill_manager_tool.py::_validate_frontmatter`): `name` (≤64 chars, lowercase+hyphens), `description` (≤1024 chars). Whole file ≤100,000 chars.
- **Two install locations:** user-local (`~/.hermes/skills/<category>/<name>/SKILL.md`) or in-repo (`<hermes-agent-root>/skills/<category>/<name>/SKILL.md`).
- **A third location relevant here — plugin-bundled skills:** `PluginContext.register_skill()` (`hermes_cli/plugins.py:1037-1080`) lets a plugin ship its own `SKILL.md` under its own directory, resolved via `skill_view("<plugin-name>:<skill-name>")`. Documented at `website/docs/guides/build-a-hermes-plugin.md:383-424` ("Bundle skills"). Per that doc, plugin-bundled skills are **not** auto-listed in the system prompt's skill index — they must be explicitly loaded (by qualified name, a `/command`, or a cron `--skills` reference).

There is no distinct "agent definition" format beyond this — "agent" in Hermes' own documentation refers to the whole framework, not a per-workflow config object.

## 2. How a channel message invokes a skill

Two independent paths, both verified against `gateway/run.py` and `agent/`:

**a) Explicit `/command`.** `gateway/platforms/base.py:1469-1485` — `MessageEvent.is_command()` is `text.startswith("/")`. Only then does `gateway/run.py:7405-7483` dispatch: plugin-registered commands first (`register_command()`), then skill *bundles*, then individual skill commands via `agent/skill_commands.py::resolve_skill_command_key()` (slug derived from the skill's `name:` frontmatter). A matched skill is loaded and its content is spliced into a synthesized activation message (`build_skill_invocation_message()`, `agent/skill_commands.py:432-476`), which then proceeds through the normal agent turn.

**b) Plain text — "Run my research topics." with no leading slash.** This is the case that matters for the product goal's step 4. It does **not** go through the command dispatcher at all (`is_command()` is false). Instead, the system prompt itself instructs the model to self-select skills: `agent/prompt_builder.py:1347-1360` builds a mandatory `## Skills` section telling the model *"scan the skills below... if a skill matches or is even partially relevant... you MUST load it with `skill_view(name)`... err on the side of loading."* Each skill's `name`/`description` frontmatter is what's shown in that index.

**Consequence:** natural-language triggering is soft and LLM-mediated, not a deterministic keyword router — and it only works for skills that appear in that auto-built index. Per §1, **plugin-bundled skills are opted out of that index by default.** So a plugin-bundled `amp-governance:research-agent` skill would need either (a) users to type an explicit `/research-agent`-style command, or (b) a small always-visible pointer (a regular, non-plugin-bundled skill, or a system-prompt hint) that tells the model to `skill_view("amp-governance:research-agent")` when it sees research-shaped requests — the same pattern Hermes uses for its own docs (`agent/prompt_builder.py:138`: *"Load the hermes-agent skill with skill_view(name='hermes-agent')"*).

## 3. How the workflow reads a local configuration file

No special mechanism needed. Skill instructions are just text telling the model to call the standard built-in `read_file` tool (already available in every session) on a path — e.g. `~/.hermes/research_topics.yaml`. (A distinct, narrower "skill config vars" system exists at `agent/skill_utils.py:461-520,577-618` for small values declared under `metadata.hermes.config` in frontmatter and stored in `config.yaml` — not a fit for a topics list; plain `read_file` is the right tool here.)

## 4. How it calls tools or plugin capabilities

This is the corrected part (see top of doc). Concretely, for AHP:

1. Implement `evaluate_proposed_plan()` in AHP (done this cycle — Phase 3A, see `__init__.py` and the "Plan approval (Phase 3A)" README section).
2. Register it as a tool in `register(ctx)` (not done this cycle):
   ```python
   ctx.register_tool(
       name="evaluate_proposed_plan",
       toolset="amp_governance",
       schema={...},  # {"plan": {...}} JSON schema
       handler=lambda args, **kw: _PLUGIN.evaluate_proposed_plan(args.get("session_id"), args.get("plan")),
   )
   ```
   (`hermes_cli/plugins.py:319-355`; walkthrough at `website/docs/guides/build-a-hermes-plugin.md` steps 3-5, lines 78-265.)
3. The research-agent skill's instructions then simply say: "call the `evaluate_proposed_plan` tool with the JSON plan you produced." This is a normal in-process tool call dispatched through `tools.registry`/`tool_executor` — the same mechanism used for every built-in tool — **not** a Python import (skills contain no executable code to import from) and not a separate process.

For the planning LLM call itself (producing the structured plan JSON from `research_planning_prompt.md`), two options, both grounded:
- Let the skill's own conversational LLM turn produce the JSON directly (simplest).
- Or call `ctx.llm.complete_structured(...)` (`agent/plugin_llm.py`, `website/docs/developer-guide/plugin-llm-access.md`) from inside a registered tool handler, if the plan needs to be produced by deterministic, separately-auditable plugin code rather than the main conversational turn.

Note: `evaluate_proposed_plan` is **not** importable as `from amp_governance import evaluate_proposed_plan` from outside the running Hermes process. Plugins are loaded via `importlib.util.spec_from_file_location` into a synthetic `hermes_plugins.<slug>` namespace (`hermes_cli/plugins.py:1590-1626`) — not an installable top-level package. The tool-call boundary (§4 above) is the actual integration path, not a raw import.

## 5. How Hermes cron invokes the same workflow

`hermes cron create "<schedule>" "<prompt>" --skills "amp-governance:research-agent" --name "..." --deliver telegram` — verified at the code level (not just documentation) via `hermes_cli/cron.py:187-235` (`--skill`/`--skills`/`--script` args) and `cron/scheduler.py::_build_job_prompt:1033-1233`, specifically line 1161 (`from tools.skills_tool import skill_view`) and line 1194 (`skill_view(skill_name)`) — confirming cron's skill-loading path calls the identical `skill_view()` used for slash-command and LLM-mediated loading, and accepts the qualified `"plugin:skill"` form.

A cron job's optional `--script` pre-run step (stdout injected as context, `cron/scheduler.py:1054-1081`) runs as a **separate subprocess** (`_run_job_script`, lines 970-979) — useful for pre-fetching/parsing data as text, but it cannot call in-process plugin tools like `evaluate_proposed_plan`, since it doesn't share the running process's tool registry.

## 6. Smallest viable Phase 3B implementation path

1. Add `evaluate_proposed_plan` as a registered tool in AHP's `register(ctx)` (§4).
2. Ship `~/.hermes/plugins/amp-governance/skills/research-agent/SKILL.md` via `ctx.register_skill()`, containing the planning instructions (adapted from `examples/research_planning_prompt.md`) plus a directive to read `examples/research_topics.yaml`'s real-world equivalent and call the new tool.
3. Add a small always-visible pointer (or require an explicit `/research-agent` command) so "Run my research topics." actually triggers the skill — plugin-bundled skills opt out of the automatic index (§2).
4. Enable the plugin (`hermes plugins enable amp-governance`) so the new tool/skill registrations run.
5. Optionally schedule with `hermes cron create ... --skills "amp-governance:research-agent" ...` (§5) for the recurring-run product goal.

None of this is implemented in this cycle — Phase 3A (this repo, `evaluate_proposed_plan()`) is the prerequisite it all depends on.

## Summary

| Need | Exists in Hermes today? | Where |
|---|---|---|
| Skill file format / discovery / loading | Yes | `agent/skill_commands.py`, `tools/skills_tool.py` |
| Chat message → skill dispatch (explicit `/cmd` and LLM-mediated) | Yes | `gateway/run.py:7405-7500`, `agent/prompt_builder.py:1347-1360` |
| Cron scheduling with skill preload | Yes | `hermes_cli/cron.py`, `cron/scheduler.py:1033-1233` |
| Reading a local config file from a skill | Yes (via standard `read_file`) | n/a |
| Plugin calling an LLM for structured planning | Yes | `agent/plugin_llm.py`, `ctx.llm` |
| Plugin registering a tool a skill can call | Yes (contrary to the earlier assumption) | `hermes_cli/plugins.py:319-355` (`PluginContext.register_tool()`) |
| Plugin shipping its own skill | Yes | `PluginContext.register_skill():1037-1080` |
| `evaluate_proposed_plan()` registered as a callable tool | **No — implemented this cycle as a plain method/function, not yet registered as a tool** | `__init__.py` (this repo) |
| Any tool/skill registration in AHP today | **No — AHP registers only hooks and the `llm_execution` middleware** | `__init__.py` `register()`, `plugin.yaml` |
