# Prompt-To-Manim Improvements Design

**Date:** 2026-04-24  
**Status:** Draft

---

## Goal

Improve the quality, determinism, and failure handling of the current prompt-to-Manim generation path while intentionally staying on direct Python generation in the near term.

This is the third stage in the hardening sequence and depends on:

1. stage 1: typed normalized scene input
2. stage 2: deterministic render-option bypassing

---

## Current Problem

The current generation path gives the LLM too many jobs at once:

1. parse raw scene JSON
2. infer scene structure
3. infer coordinate treatment
4. choose Manim primitives
5. sequence animation logic
6. emit final runnable Python

Even after stage 1 and stage 2 reduce some of that burden, the current prompt design remains brittle because it relies on a long prose instruction block and accepts freeform Python output with almost no validation.

---

## Design Principles

1. Keep immediate improvements within the current Python-generation architecture.
2. Reduce prompt ambiguity by separating instruction sections clearly.
3. Validate generated code before accepting it as a scene file.
4. Move deterministic preprocessing into code wherever practical.
5. Preserve a clean migration path toward structured outputs later.

---

## Proposed Immediate Improvements

### 1. Structured Prompt Builder

Replace the current ad hoc prompt concatenation with an explicit prompt builder that assembles named sections such as:

- system constraints
- normalized scene summary
- user animation intent
- coordinate/scale conventions
- output contract

The prompt should no longer rely on a raw JSON dump appended after the user prompt.

### 2. Stronger Output Contract

The model should still output Python, but the contract should become more enforceable.

Required invariants:

1. raw Python only
2. class name `GeneratedScene`
3. complete runnable module
4. allowed import shape
5. no markdown fences

### 3. Post-Generation Validation

Before writing the file, validate generated output with at least:

1. `compile()` success
2. `GeneratedScene` presence
3. import allowlist or import-shape validation
4. optional AST checks for obviously invalid scene structure

If validation fails, the system should either:

- fail fast with a clear generation error, or
- run a tightly scoped repair pass

The design should prefer one explicit policy. Recommended initial policy:

- implement validation first
- add repair only if needed after observing failure patterns

### 4. Better Generation Traceability

Persist or return generation metadata alongside the scene file, such as:

- normalized scene hash
- prompt version
- model identifier
- render options hash

This is valuable for debugging regressions and comparing improvements over time.

---

## Suggested Architecture

Recommended internal layering inside `layersense_agent`:

1. scene normalization layer from stage 1
2. render-option extraction layer from stage 2
3. prompt builder service
4. generation service wrapper around model invocation
5. code validation service
6. file write + metadata persistence

The endpoint should orchestrate these steps, not contain all generation logic inline.

---

## Failure Handling

Current generation failures are deferred too late. Invalid Python often survives until controller render time.

This stage should move obvious failures into the agent layer.

Recommended failure categories:

1. invalid request / normalization failure
2. generation failure
3. generated code validation failure
4. file write failure

The agent should return clearer failure semantics so the controller only renders known-good scene files.

---

## Testing Strategy

### Prompt Builder Tests

Add tests for:

1. prompt section assembly
2. omission of bypassed deterministic fields
3. stable formatting for equivalent inputs

### Validation Tests

Add tests for:

1. valid generated Python accepted
2. markdown-fenced output rejected or normalized
3. missing `GeneratedScene` rejected
4. syntax errors rejected
5. invalid import shape rejected

### Endpoint/Generation Tests

Add tests for:

1. validated code is written successfully
2. invalid output fails before controller handoff
3. generation metadata is recorded correctly

---

## Non-Goals

This stage does not:

1. replace Python generation with a structured-output compiler architecture
2. change the frontend user flow materially
3. expand controller responsibility beyond consuming explicit render options

---

## Risks And Tradeoffs

### Risk: validation becomes too strict and blocks usable outputs

Mitigation:

- start with structural checks, not subjective code-style checks

### Risk: prompt changes improve one scene family and hurt another

Mitigation:

- create representative regression fixtures for rectangles, ellipses, and freedraw scenes

### Risk: adding repair too early hides real prompt defects

Mitigation:

- treat repair as optional follow-up, not default scope

---

## Acceptance Criteria

1. Prompt construction is handled by a dedicated builder, not simple string concatenation.
2. Generated Python is validated before the scene file is accepted.
3. Invalid generation fails in the agent layer rather than being deferred to controller render.
4. The current direct-Python generation path remains the implementation target.
5. Generation behavior is easier to debug via recorded metadata and clearer contracts.

---

## Outlook

The long-term architecture should likely move beyond direct Python generation.

The most promising future direction is:

1. the LLM emits a structured animation plan or animation IR
2. deterministic application code compiles that plan into Manim Python
3. validation shifts from freeform code checking toward schema validation and compiler correctness

That architecture is not the implementation target of this stage, but this stage should avoid blocking it. In particular:

- prompt-builder boundaries should be explicit
- normalized scene IR should stay reusable
- validation and metadata layers should not assume Python generation is permanent
