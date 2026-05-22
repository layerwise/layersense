# OpenCode-Style Agentic Runtime — Decision Plan

**Status:** Speculative — decision plan, not implementation plan. Normalized 2026-05-21 against `docs/plans/2026-05-21-architecture-expansion-overview.md`. Evidence comes from the qualitative Step 7 agent friction log, not from metrics instrumentation.
**Step in build order:** 9 of 9
**Depends on:** Step 7 (multi-file projects + components library, Agent Tier 2) — must be in real use before this decision has inputs
**Unblocks:** nothing in the current migration; a "proceed" decision opens a new implementation track outside this 9-step plan

**Amendment (2026-05-22):** Evidence model changed to friction-log-only (decision #18). Quantitative thresholds and metrics.json dependency removed. Option C framing clarified as potentially superseded. Per audit findings 9.1, 9.3-9.4.

---

## Why this step exists

When Mathias first described the architecture expansion, one of the three initiatives was: *"agent powered by an OpenCode-style intelligent agentic workflow."* The original vision was an agent that could reason about a whole project, navigate files, run tools, and iterate — not just receive a payload and return bytes.

During the architecture conversation, that vision was deferred rather than abandoned. The reasoning:

1. **The pure-function agent (Option C) is the right default.** It is simple, testable, replaceable, and sufficient for single-scene generation. Introducing a richer runtime before hitting real limits would add complexity with no demonstrated payoff.
2. **Step 7 is the natural stress test.** Multi-file projects with a shared components library are where a pure-function agent first encounters real cross-file reasoning demands. If the agent struggles there, the evidence will be concrete and actionable.
3. **The decision should be evidence-driven, not vision-driven.** This step preserves the option to swap the runtime while ensuring the swap is justified by observed friction, not anticipated friction.

This plan exists to define what "justified" means, how to collect the evidence, and what the swap looks like if the decision is yes.

---

## The decision this plan exists to make

> **Should the agent runtime be swapped from the current pure-function LLM call (via `openai-agents`) to a heavier code-agent harness that can reason about, navigate, and iteratively modify a multi-file project?**

This is a binary decision with a third option:

- **Yes, swap:** adopt a richer runtime (OpenCode, Claude Agent SDK, custom tool harness, etc.) inside the agent process.
- **No, don't swap:** invest the same effort in smarter payload assembly, better prompting, and controller-side refinement automation.
- **Partial:** extend the existing `openai-agents` tool surface without adopting a new runtime framework — the lowest-cost path to richer agent behavior.

The decision must be made with evidence. This plan defines what qualitative evidence to collect and what friction patterns trigger each outcome.

---

## Triggers to evaluate

The following observable conditions from Step 7 usage would warrant formally evaluating the swap. Any single trigger at sufficient frequency is enough to open the evaluation; multiple triggers together make the case stronger.

### T1 — Cross-file import failures
The agent generates code that imports from a component or utility that exists in the project but was not included in the payload. The generated scene fails at Manim render time with an `ImportError` or `ModuleNotFoundError`. The fix requires a second generate/refine cycle that would have been unnecessary if the agent had seen the full project.

### T2 — Payload size approaching context limits
The controller's payload assembly (scene JSON + prompt + component files + previous render source) consistently approaches or exceeds the model's effective context window. Symptoms: truncated context warnings, degraded generation quality on large projects, or explicit token-limit errors.

### T3 — Refinement loops that should have been single-shot
A user refines a scene 3+ times in a row where each refinement is fixing a problem the agent introduced (not a user preference change). The agent is iterating toward a solution it should have reached in one pass. This is the "agent feels too dumb for the task" signal.

### T4 — Component reuse failures
The agent generates new utility code (color palettes, animation helpers, layout functions) that duplicates existing components in the project's `components/` directory. The agent doesn't know what already exists.

### T5 — Structural incoherence across scenes
Scenes within the same project use inconsistent naming, style, or structure in ways that a project-aware agent would have avoided. The user has to manually harmonize scenes that should have been coherent by default.

---

## Evidence-gathering plan for Step 7

**Evidence model (design decision #18):** The go/no-go decision is based on a qualitative friction log maintained at `docs/decisions/step-7-agent-friction-log.md` during Step 7 usage. Quantitative metrics (render time, token count, etc.) and the `metrics.json` sidecar are dropped — they created a dependency on instrumentation that Step 7 does not ship.

Decision criteria: the friction log documents specific cases where the inline FileBundle model caused measurable developer friction (failed generations, manual workarounds, scope limitations). If 3+ distinct friction patterns emerge that a tool surface would resolve, proceed with evaluation. Otherwise, the pure-function model is confirmed adequate.

### What to track manually

Keep a running tally in `docs/decisions/step-7-agent-friction-log.md` (created when Step 7 ships). For each session where the agent produces a broken or unsatisfying result, record:

- Which trigger (T1–T5) best describes the failure
- How many refinement cycles were needed
- Whether the fix was "add more context to payload" or "the agent needed to reason differently"

This is a 2-minute-per-incident log. The goal is to identify distinct friction patterns, not to hit a numerical telemetry threshold.

### When to collect

Start collecting from the first real Step 7 usage. Do not wait for Step 9 to formally begin.

---

## Decision criteria

### Friction-log criteria

- **User frustration signal:** Mathias explicitly describes the agent as "too dumb for the task" on multiple occasions, not as a one-off.
- **Payload assembly ceiling:** The controller's smart payload assembly (Step 7's "include relevant files" logic) has been tuned and still doesn't solve the problem. The issue is reasoning, not context.
- **Diminishing returns on prompting:** Prompt engineering improvements have been tried and the failure modes persist.
- **Tool-surface fit:** 3+ distinct friction patterns emerge that a file/tool surface would plausibly resolve better than inline `FileBundle` payloads.

### Criteria for "do not proceed"

- Fewer than 3 distinct tool-surface-resolvable friction patterns appear after 4+ weeks of real Step 7 usage entries.
- The failures that do occur are fixable by improving payload assembly or prompting, not by changing the runtime.
- The user's actual workflow doesn't stress the agent enough to generate meaningful evidence (i.e., Step 7 is used lightly).

---

## Candidate runtimes

### Option A: OpenCode (user's original mention)

**What it is:** OpenCode is an agentic coding assistant runtime that wraps an LLM with a rich tool surface (file read/write, shell execution, search) and a structured conversation loop. It is designed to operate on a real filesystem, not an in-memory payload.

**What it provides:** Full project awareness via filesystem tools; iterative self-correction; structured tool call loops.

**Integration cost:** High. OpenCode is designed as a standalone CLI/service, not as an embeddable library. Integrating it as the agent's internal runtime would require either spawning it as a subprocess (fragile) or extracting its tool-loop pattern into the agent codebase (significant rewrite). The agent's HTTP boundary would need to change: instead of returning bytes synchronously, it would need to run an async tool loop and return when done.

**Option C impact:** This step evaluates whether Option C should be amended. If the friction log justifies a tool surface, Option C is explicitly superseded for the agent's role in Step 7+ workflows. The risk is that OpenCode's filesystem tools would want to operate on a real project directory, which means the controller would need to materialize the project to a temp directory before calling the agent — a significant change to the worker flow.

**Verdict:** High integration cost, unclear embeddability. Treat as inspiration for the tool surface design, not as a drop-in runtime.

---

### Option B: Claude Agent SDK (Anthropic)

**What it is:** Anthropic's first-party SDK for building agents with tool use, structured outputs, and multi-turn conversation management. Mature, well-documented, designed for embedding.

**What it provides:** Clean tool-call loop, structured tool definitions, streaming support, built-in retry/error handling.

**Integration cost:** Medium. The agent already uses `openai-agents`; switching to Claude Agent SDK means changing the LLM provider and the tool-loop abstraction. The agent's HTTP boundary stays unchanged. Tool implementations (read/write/search) would be written against the SDK's tool interface.

**Does Option C survive?** Yes. The SDK runs inside the agent process. The controller's view is unchanged.

**Verdict:** Viable if the decision is to proceed and the team is comfortable with Anthropic lock-in. The tool surface would be custom-built, not inherited from a framework.

---

### Option C: OpenAI Assistants API / Responses API with tools

**What it is:** OpenAI's hosted agent runtime. Assistants API manages conversation threads, file attachments, and tool calls server-side. Responses API (newer) provides a stateless tool-call loop.

**What it provides:** Hosted state management, code interpreter, file search, custom tool calls.

**Integration cost:** Medium-high. The Assistants API's thread model doesn't map cleanly to the pure-function agent shape — threads are stateful and hosted, which conflicts with the "agent is stateless" property. The Responses API is closer to the current shape but still requires adapting the tool-call loop.

**Does Option C survive?** Partially. The agent's HTTP boundary can stay pure-function, but the agent would be making outbound calls to OpenAI's hosted runtime, introducing a new external dependency and latency.

**Verdict:** The code interpreter tool is genuinely useful for Manim (it can run Python and catch errors). But the hosted-state model is architecturally awkward. Worth evaluating if the decision is to proceed, but not the first choice.

---

### Option D: Extend `openai-agents` with a richer tool surface (minimal-cost path)

**What it is:** The agent already uses `openai-agents`. Add custom tools (`read_file`, `write_file`, `list_dir`, `run_manim_check`) that operate on a materialized project directory inside the agent's process. No new framework; same tool-loop abstraction.

**What it provides:** Project-aware file navigation and iterative self-correction, without adopting a new runtime. The agent can read component files, check imports, and fix its own output before returning.

**Integration cost:** Low-medium. The controller materializes the project to a temp directory before calling the agent (or passes a structured file manifest in the payload). The agent's tool calls operate on that temp directory. The HTTP boundary changes slightly: the payload gains a `project_files` map or a `project_dir` path; the response is still raw source bytes.

**Does Option C survive?** Yes, with a minor relaxation: the agent is no longer purely stateless during a single call (it has a temp directory), but from the controller's view it is still input-payload → output-bundle. The "pure function" property is preserved at the HTTP boundary.

**Verdict:** This is the recommended first step if the decision is to proceed. It is the lowest-cost path to richer agent behavior and preserves the most architectural properties. It is also reversible: the tool surface can be extended incrementally without committing to a new framework.

---

### Option E: Local agent frameworks (AutoGen, LangGraph, Pydantic AI)

**What they are:** Open-source multi-agent orchestration frameworks. AutoGen and LangGraph are designed for multi-agent workflows; Pydantic AI is a lightweight agent framework with strong typing.

**What they provide:** Structured agent graphs, multi-agent coordination, tool call management.

**Integration cost:** Medium-high for AutoGen/LangGraph (they are designed for multi-agent workflows, which is overkill for a single code-generation agent). Pydantic AI is lighter and closer to the current `openai-agents` shape.

**Does Option C survive?** Yes for all three, if the framework runs inside the agent process.

**Verdict:** Pydantic AI is worth evaluating as a drop-in replacement for `openai-agents` if the tool surface needs to grow. AutoGen and LangGraph are overkill for this use case.

---

## If proceed: architecture sketch

The key architectural question is: **does the agent gain the ability to call back to the controller (violating Option C purity), or does the controller still package everything?**

**Recommendation: the controller still packages everything. The richer runtime is an implementation detail of the agent service.**

### What changes

**Controller worker (Step 7 flow):**
- Before calling the agent, the worker materializes the project's relevant files to a temp directory: `components/`, `assets/`, and the current scene's source (if refining).
- The agent payload gains a `project_context` field: either a structured file manifest (`{path: content}` map) or a reference to the temp directory path (if agent and worker share a filesystem, which they do in the compose stack).
- After the agent returns, the worker cleans up the temp directory.

**Agent service:**
- The agent's `POST /api/v1/animation` gains a `project_context` field in the request body.
- Internally, the agent materializes the project context to a working directory, runs the tool loop (using Option D's `openai-agents` tool surface or a chosen framework), and returns the final source bytes.
- The agent's response shape is unchanged: `{ scene_py_bytes, content_hash }`.

**What stays the same:**
- The controller's view of the agent: input-payload → output-bundle.
- The agent has no `controller_base_url`, no DB access, no ObjectStore access.
- The browser never calls the agent.
- The render dedup logic is unchanged.

### What the tool surface looks like (Option D path)

```python
# Inside the agent process, operating on a materialized temp directory
tools = [
    read_file(path: str) -> str,          # read a component or asset file
    list_dir(path: str) -> list[str],     # list files in a project subdirectory
    write_draft(path: str, content: str), # write a draft scene file
    check_imports(path: str) -> list[str] # parse imports, return missing ones
]
```

The agent's tool loop: generate → check imports → read missing components → regenerate → return. This loop runs inside the agent process, invisible to the controller.

---

## If not proceed: alternative investments

If the evidence does not meet the friction-log criteria, invest the same effort in:

### A1 — Smarter payload assembly in the controller

Step 7's payload assembly is intentionally simple: include all component files. The smarter version:
- Parse the scene's existing source (if refining) to extract imports.
- Only include component files that are actually imported or likely to be needed.
- Trim large asset files to summaries or type stubs.

This reduces payload size and focuses the agent's context on what matters. It is a controller change, not an agent change.

### A2 — Automatic refinement on Manim CLI errors

When a render fails with a Manim error, the controller automatically queues a refinement cycle with the error trace appended to the prompt. No user action required. The agent receives: previous source + error trace + "fix this" instruction.

This addresses T3 (refinement loops that should have been single-shot) without changing the agent runtime. The agent is still a pure function; the controller is doing the iteration.

### A3 — Better refinement context

Always include in the refinement payload:
- The full Manim error trace (not just the error message).
- The diff between the previous source and the current source (if the user edited manually).
- The list of component files that exist in the project (even if not included in full).

This is a cheap improvement to the existing refinement flow (Step 5) that reduces T1 and T3 failures.

### A4 — Prompt engineering for project awareness

Add a structured "project manifest" section to the agent's system prompt when operating in a multi-file project context:

```
Project: {project_name}
Existing components: {component_list}
Existing scenes: {scene_list}
Style conventions: {extracted_from_existing_scenes}
```

This is a zero-infrastructure improvement that gives the agent project awareness without changing the runtime.

---

## Acceptance criteria

This step produces a decision, not code. The deliverable is:

**`docs/decisions/2026-XX-XX-agent-runtime-decision.md`**

That document must contain:
1. The evidence collected from the Step 7 friction log.
2. Which friction patterns were found and whether 3+ distinct tool-surface-resolvable patterns emerged.
3. The chosen direction (swap / don't swap / partial).
4. The rationale.
5. If proceeding: a link to the new implementation plan.
6. If not proceeding: which alternative investments (A1–A4) are prioritized.

The decision document is the only acceptance criterion for Step 9. No code ships as part of this step.

---

## Risks

### R1 — Premature swap (high cost, low payoff)
Swapping the runtime before hitting real limits adds weeks of implementation work, increases system complexity, and may not improve the user experience meaningfully. The friction-log criteria in this plan are designed to prevent this, but the risk is real if the criteria are set too low or the evidence is interpreted too generously.

**Mitigation:** The friction-log criteria are conservative. Require 3+ distinct tool-surface-resolvable friction patterns before proceeding.

### R2 — Too-late swap (Step 7 friction users would otherwise abandon over)
If the agent is genuinely too limited for Step 7 workflows and the decision is deferred too long, the user's experience degrades and the tool becomes frustrating to use. The friction log is the early warning system.

**Mitigation:** The friction log is a low-overhead signal. If T1–T5 triggers are appearing in every session, don't wait for the formal decision window — escalate.

### R3 — Analysis paralysis (the decision is never made)
The evidence is "not enough yet" indefinitely. Step 7 is used lightly, the friction log stays sparse, and the decision is perpetually deferred.

**Mitigation:** Evaluation begins after the friction log accumulates 4+ weeks of real Step 7 usage entries. If the log remains sparse, the agent is not being stressed enough to justify a swap.

### R4 — Option C purity erodes during the swap
A runtime swap introduces pressure to give the agent more direct access to project state (ObjectStore, DB). Each concession makes the architecture harder to reason about.

**Mitigation:** The architecture sketch above is explicit: the richer runtime runs inside the agent process; the controller's view of the agent is unchanged. Any proposal that requires the agent to call back to the controller is out of scope.

---

## Estimated shape

| Phase | Effort |
|---|---|
| Evidence collection (friction log during Step 7 usage) | Low-overhead manual logging |
| Active evidence gathering (Step 7 usage) | Begins after the friction log accumulates 4+ weeks of real Step 7 usage entries |
| Decision writeup | 1 day |
| **Total for the decision itself** | **~1 week of elapsed time, ~2 days of active work** |
| Implementation if proceed (Option D path) | 2–3 weeks |
| Implementation if proceed (new framework path) | 4–6 weeks |
| Implementation if not proceed (A1–A4) | 1–2 weeks per investment |

The evaluation itself is cheap. The implementation cost depends entirely on the decision.

---

## Assumptions

Surface aggressively — these are the most likely sources of plan failure.

**A1 — Step 7 will produce usable evidence.**
Assumes Step 7 is actually implemented and used with real multi-file projects. If Step 7 is implemented but only used with single-scene projects, the evidence will be sparse and the decision will default to "do not proceed."

**A2 — The user will use Step 7 enough to generate meaningful evidence.**
This is a single-user tool. If Mathias doesn't use it heavily in the weeks after Step 7 ships, the friction log stays empty. Evaluation begins only after 4+ weeks of real Step 7 usage entries accumulate.

**A3 — The pure-function agent shape is the bottleneck, not the prompts.**
The friction-log criteria assume that the failures are architectural (the agent can't see enough of the project) rather than prompt-engineering failures (the agent isn't instructed well enough). If prompt improvements fix the failures, the runtime swap is not warranted. The "diminishing returns on prompting" qualitative criterion is the check on this assumption.

**A4 — Runtime choice is reversible (with cost).**
Swapping to a new runtime is not irreversible, but it is expensive to undo. The architecture sketch above minimizes lock-in by keeping the agent's HTTP boundary unchanged, but the internal implementation would be significantly different. Treat the decision as "expensive to reverse" rather than "irreversible."

**A5 — The agent's context window is the binding constraint, not latency or cost.**
The criteria focus on context-window pressure and reasoning failures. If the binding constraint turns out to be latency (the agent is too slow for interactive use) or cost (the agent is too expensive for heavy use), the decision framework needs to be revisited.

**A6 — Option D (extending `openai-agents`) is actually lower cost than adopting a new framework.**
This assumes the `openai-agents` tool surface is extensible enough to support the needed tools without fighting the framework. If `openai-agents` turns out to be poorly suited for custom tool loops, the cost estimate for Option D is wrong.

---

## Key design questions (open, for the decision document to resolve)

1. **Is the speculative/decision-focused framing the right one, or should this be a concrete "swap to X" plan?**
   Recommendation: keep it decision-focused. The user's original mention of OpenCode was visionary; the architecture conversation explicitly deferred it. Concretizing it now would be premature. If the evidence is strong, the decision document will naturally become a concrete plan.

2. **Should evidence collection start now or later (only after Step 7 is in heavy use)?**
   Recommendation: start the friction log when Step 7 ships. Do not add a `metrics.json` sidecar or quantitative instrumentation dependency.

3. **Does Option C (agent as pure function) survive a runtime swap?**
   Recommendation: yes, even with a richer runtime inside the agent process. The agent's HTTP boundary stays pure-function from the controller's view. The richer runtime is an implementation detail. Any proposal that requires the agent to call back to the controller violates Option C and should be rejected.

4. **Is OpenCode the right candidate, or should the survey be wider?**
   Recommendation: wider survey. OpenCode was the user's initial wording, but the landscape includes Claude Agent SDK, Pydantic AI, and the minimal-cost Option D path. The survey above covers the realistic candidates; OpenCode is included but not privileged.
