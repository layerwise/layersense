# Excalidraw Prompt Bypassing Design

**Date:** 2026-04-24  
**Status:** Draft

---

## Goal

Move deterministic, non-creative information out of the freeform LLM prompt and into explicit runtime contracts, starting from the normalized scene model introduced in stage 1.

This is the second stage in the Excalidraw -> agent -> controller hardening sequence and depends on the model-specificity stage being in place first.

---

## Current Problem

Today the agent serializes the full Excalidraw scene into JSON and appends it to the natural-language prompt. Any Excalidraw-derived field only affects rendering if the model notices it, interprets it correctly, and writes corresponding Python.

This is the wrong place for deterministic information such as:

- render background color
- scene bounds-derived framing hints
- asset metadata
- other render-safe fields that do not need creative interpretation

The result is unnecessary instability. The prompt currently carries both creative intent and deterministic configuration, even though only the former should require LLM judgment.

---

## Design Principles

1. The prompt should carry creative intent, not low-level runtime facts.
2. Only allowlist fields should bypass the prompt into the render path.
3. Render-affecting options must become part of cache identity.
4. The bypass layer should depend on the normalized scene IR, not raw Excalidraw JSON.
5. This stage should keep the main generate output as Python scene code.

---

## Proposed Data Split

After stage 1 normalization, generation input should be split into three conceptual buckets:

1. `user_intent`
   - the user prompt and any explicitly LLM-relevant framing

2. `generation_scene`
   - normalized scene facts that the model still needs for code generation

3. `render_options`
   - deterministic fields injected directly into render job/configuration

The key change in this stage is formalizing `render_options` as a first-class contract.

---

## Recommended Initial Bypass Fields

### 1. Background Color

Initial direct extraction target:

- `scene.appState.viewBackgroundColor`

This should become `render_options.background_color` and be applied directly by the controller's render configuration instead of being left for the model to encode into Python scene logic.

This is the cleanest first bypass because:

1. it already exists in the Excalidraw payload
2. it maps directly to Manim render config
3. it does not require creative interpretation

### 2. Scene Bounds Metadata

Scene bounds should be computed deterministically from normalized elements and carried as structured metadata.

Examples:

- min/max x and y
- scene width and height
- aspect-ratio hint

This metadata may still help prompt construction, but the computation itself should not be delegated to the model.

### 3. Asset Manifest

If `scene.files` is present and relevant, it should be normalized into a validated asset manifest rather than dumped into the prompt. This stage does not need to fully solve asset rendering, but it should create the contract boundary for doing so.

---

## Render Contract Changes

The current controller render request accepts only:

- `scene_path`
- `conversation_id`

This stage should extend the contract to include explicit render options. For example:

- `render_options.background_color`
- optionally `render_options.aspect_ratio_hint` or equivalent structured metadata
- optional asset-related fields if validated and supported

The exact contract should remain small. Do not pass raw `appState` or raw Excalidraw scene fragments into the controller.

---

## Controller Changes

The controller currently renders using fixed package-owned config files with hardcoded values such as `background_color = BLACK`.

This stage should keep package-owned defaults, but allow per-job overrides for allowlisted render options.

Recommended controller behavior:

1. keep static preview/final defaults as the base config
2. overlay per-render options at execution time
3. only allow known-safe fields to override config

This should not become an arbitrary config passthrough API.

---

## Cache Identity Changes

Current artifact caching is content-hash based on the generated scene file.

That is insufficient once render options are injected outside the scene code. For example, the same Python scene rendered with two different background colors must not collide.

This stage therefore requires cache identity to incorporate render options.

Recommended rule:

- cache key = hash(scene file content + normalized render options)

This keeps caching correct without requiring broad architectural change.

---

## Agent Changes

The agent should stop treating full scene JSON as the main prompt payload.

In this stage, that means:

1. normalize scene input from stage 1
2. extract `render_options`
3. pass only the generation-relevant subset into prompt construction
4. return or persist enough structured metadata for the frontend/controller handoff

This stage does not yet redesign the generation system around structured LLM output. It only reduces prompt responsibility by removing deterministic fields from it.

---

## Frontend Changes

The frontend currently posts the Excalidraw snapshot to the agent and separately queues a render based on the agent response.

This stage should preserve that basic user flow, but the data contract will likely expand so the controller receives explicit render options sourced from the normalized scene.

Recommended principle:

- the frontend should not compute render options itself beyond transmitting structured values returned by the agent or already formalized by contract

This keeps normalization logic server-side and consistent.

---

## Testing Strategy

### Agent Tests

Add tests for:

1. `viewBackgroundColor` extraction into render options
2. scene-bounds derivation from normalized elements
3. prompt assembly excluding bypassed fields

### Controller Tests

Add tests for:

1. render option application to preview/final render execution
2. render option allowlist enforcement
3. cache differentiation when render options differ

### End-to-End Tests

Add or update coverage proving:

1. an Excalidraw background color survives the full stack
2. controller output uses the explicit render option path, not just prompt-side generation luck

---

## Non-Goals

This stage does not:

1. replace Python generation with a compiler pipeline
2. support arbitrary Excalidraw field passthrough into render config
3. solve all asset semantics
4. redesign the browser UX

---

## Risks And Tradeoffs

### Risk: too much logic added to the controller contract

Mitigation:

- keep the render options contract tightly allowlisted
- move only deterministic fields

### Risk: cache bugs during transition

Mitigation:

- make render-option hashing explicit and tested

### Risk: duplicated logic between agent and controller

Mitigation:

- keep the agent responsible for extraction and normalization
- keep the controller responsible for application and validation

---

## Acceptance Criteria

1. `viewBackgroundColor` bypasses the LLM prompt and is injected directly into the render job.
2. The controller accepts explicit render options instead of relying only on scene code.
3. Cache identity changes when render options change.
4. The prompt contains less deterministic payload noise than before.
5. The generate -> queue render -> websocket flow remains intact.

---

## Sequencing Note

This stage assumes the typed normalized scene contract from stage 1.

Stage 3 will build on this by improving prompt construction and Python generation quality, now that deterministic render concerns have already been pulled out of the prompt path.
