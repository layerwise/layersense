# Excalidraw Model Specificity Design

**Date:** 2026-04-24  
**Status:** Draft

---

## Goal

Replace the current raw Excalidraw payload passthrough contract with a typed, validated, normalized scene model while keeping the current Python-generation runtime behavior intact.

This is the first stage in a three-stage hardening sequence:

1. Model specificity
2. Excalidraw prompt bypassing
3. Prompt-to-Manim improvements

Later stages depend on this stage producing a stable, trustworthy scene contract.

---

## Current Problem

The live request boundary accepts Excalidraw payloads as broad dictionaries:

- `elements: list[dict[str, Any]]`
- `appState: dict[str, Any]`
- `files: dict[str, Any]`

That contract exists in `layersense_agent/src/layersense_agent/models/base.py` and is effectively a bag-of-JSON API.

The repository also contains a stricter Excalidraw model in `layersense_agent/src/layersense_agent/models/scene.py`, but it is not wired into the live request path and does not fully match current payload reality.

This creates three problems:

1. The agent prompt is built from unvalidated scene data.
2. Later deterministic extraction work has no canonical typed source.
3. Tests currently lock in permissive passthrough behavior instead of the intended contract.

---

## Design Principles

1. Accept broad external input, but normalize immediately.
2. Keep a small internal scene IR that matches what LayerSense actually understands today.
3. Preserve raw payload access only where it serves debugging or future migration.
4. Avoid pretending the system supports every Excalidraw element if it does not.
5. Keep this stage behavior-preserving for the generate -> write scene file path.

---

## Proposed Contract Shape

### External Request Contract

The frontend continues to send the same top-level shape:

- `prompt: string`
- `scene: object`

This stage does not require a frontend API redesign.

### Internal Normalized Scene Contract

The agent should normalize incoming Excalidraw data into a typed internal model with these responsibilities:

- `NormalizedScene`
  - `elements: list[NormalizedElement]`
  - `app_state: NormalizedAppState`
  - `files: NormalizedFiles`
  - optional `raw_scene` or equivalent debug-only access if needed during migration

- `NormalizedElement` should be a discriminated union keyed by `type`
  - `RectangleElement`
  - `EllipseElement`
  - `FreedrawElement`

Element variants should expose only fields the current system can meaningfully use, such as:

- geometry: `x`, `y`, `width`, `height`, `angle`
- appearance: `strokeColor`, `backgroundColor`, `fillStyle`, `strokeWidth`, `strokeStyle`, `opacity`
- `points` only for `freedraw`
- identifiers needed for ordering/debugging such as `id`

`NormalizedAppState` should stay intentionally small in this stage. The only field that is clearly worth formalizing now is:

- `viewBackgroundColor`

Other app-state fields should remain optional and only be promoted when a later stage consumes them intentionally.

`NormalizedFiles` can initially remain permissive, but behind a named type instead of anonymous dicts.

---

## Validation Rules

This stage should enforce only the rules needed to establish a dependable contract:

1. Reject malformed element objects.
2. Reject unsupported element `type` values from the normalized path.
3. Require `points` for `freedraw` elements.
4. Require geometry for shape elements.
5. Treat `appState` as partial, not all-fields-required.
6. Filter or ignore deleted/non-render-relevant elements if present.

If unsupported elements are present, the normalization layer should choose one explicit policy and document it. Recommended policy:

- keep unsupported elements out of the normalized IR
- record them in debug metadata if needed
- do not fail the whole request unless the scene becomes unusably empty

This keeps the stage practical while avoiding false claims of full Excalidraw coverage.

---

## Backend Architecture Changes

This stage should concentrate changes inside `layersense_agent`.

Recommended structure:

- `models/base.py`
  - keep request/response API models focused on transport
- `models/scene.py`
  - define the normalized typed scene models used by the agent
- new normalization service, for example `services/scene_normalizer.py`
  - accept incoming request scene payload
  - validate and convert to normalized IR
- endpoint layer
  - validate request
  - normalize scene
  - pass normalized scene forward to generation flow

The controller and frontend should remain functionally unchanged in this stage, except for any safe typing improvements on the frontend side.

---

## Frontend Typing Changes

The frontend currently types Excalidraw snapshots as `unknown[]` and `Record<string, unknown>`.

This stage should improve TypeScript typing to better reflect actual Excalidraw API return values, but without changing browser behavior. The frontend still captures:

- `getSceneElements()`
- `getAppState()`
- `getFiles()`

The goal is contract clarity, not frontend feature changes.

---

## Testing Strategy

This stage needs contract tests more than runtime-behavior tests.

### Agent Unit Tests

Add tests for:

1. valid rectangle normalization
2. valid ellipse normalization
3. valid freedraw normalization
4. missing required freedraw points
5. partial `appState` acceptance
6. unsupported element handling
7. empty-or-effectively-empty scene handling

### Endpoint Tests

Add tests proving:

1. the endpoint accepts the current browser payload shape
2. normalization happens before prompt construction
3. malformed payloads fail early and explicitly

### Frontend Tests

Only add or update tests if typing changes require it. This stage should avoid frontend behavior churn.

---

## Non-Goals

This stage does not:

1. inject render settings into controller jobs
2. redesign the prompt format
3. change the controller render contract
4. move to structured LLM outputs
5. broaden Excalidraw feature support beyond the currently useful subset

---

## Risks And Tradeoffs

### Risk: overfitting the schema too early

If the normalized model is too narrow, later scene support becomes harder.

Mitigation:

- keep the internal IR small but intentionally extensible
- preserve raw payload access during migration

### Risk: breaking current permissive tests

Current tests encode passthrough behavior.

Mitigation:

- replace those tests with explicit normalization-contract tests
- document the contract change clearly

### Risk: mismatch with real Excalidraw payloads

The existing strict model already appears stale.

Mitigation:

- align the normalized model with live payload examples before enforcing it

---

## Acceptance Criteria

1. The live agent path no longer depends on `list[dict[str, Any]]` for scene elements.
2. The system has a canonical typed normalized scene model used by the generation path.
3. `appState` is validated as a partial contract, not an all-fields-required object.
4. Supported element families are explicit and tested.
5. Current generate -> write scene file behavior remains intact.

---

## Sequencing Note

This stage exists to support stage 2 and stage 3.

Stage 2 will extract deterministic render/runtime fields from this normalized scene contract.
Stage 3 will improve prompt-to-Manim generation using this contract as the input source instead of raw scene JSON.
