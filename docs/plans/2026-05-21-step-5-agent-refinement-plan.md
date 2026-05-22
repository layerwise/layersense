# Agent Refinement (Tier 1) — Implementation Plan

**Status:** Proposed. Normalized 2026-05-21 against `docs/plans/2026-05-21-architecture-expansion-overview.md`. Canonical source-key form: `renders/{content_hash}/source.py`. Migration number is `0004` per the normalized sequence (Step 5 = 0004, Step 6 = 0005, Step 7 = 0006).
**Step in build order:** 5 of 9
**Depends on:** Step 4 (`POST /api/v1/scenes/{id}/generate`, controller-as-orchestrator, `parent_render_id` column in `Render`) merged
**Unblocks:** Step 6 (project export), Step 7 (multi-file project + agent Tier 2)

---

## Why this step

After Step 4, the user can generate a Manim animation from a scene and watch it render. But every "Generate" starts from scratch — the LLM has no memory of what it just produced. If the user wants to change one thing ("make the circle red instead of blue"), they must re-describe the entire scene from scratch and hope the LLM reconstructs the rest faithfully.

This step adds **iterative refinement**: the user can click "Refine" next to "Generate", type a short delta prompt ("make the circle red"), and the controller feeds the previous render's source code back to the agent as inline context alongside the new instruction. The agent can then produce a minimal diff rather than a full rewrite.

The mechanism is lightweight: no new agent infrastructure, no new queue, no new worker. The same pure-function agent shape from Step 4 gains one additional optional field (`previous_source_code`). The controller gains one new endpoint (`POST /api/v1/scenes/{id}/refine`) that assembles the richer payload. The `parent_render_id` column already exists in the `Render` schema from Step 2 — this step makes it non-null for refinement renders.

**Why now (before Step 6/7)?** Refinement is the most common creative loop: generate → watch → tweak → watch. Without it, every iteration is a full regeneration. This is the highest-leverage UX improvement available at this point in the build order, and it requires no new infrastructure beyond what Step 4 already ships.

---

## Scope

### In scope

1. **Controller endpoint** `POST /api/v1/scenes/{id}/refine { refinement_prompt, cli_flags? }`.
2. **Controller task** `refine_and_render(render_id)` — same Taskiq task shape as `generate_and_render`, with the additional step of reading the previous render's source from ObjectStore and including it in the agent payload.
3. **Agent contract extension**: `POST /api/v1/animation` gains three new optional fields: `previous_source_code`, `previous_prompt`, `refinement_prompt`. When present, the agent's prompt-construction logic uses them as structured context. When absent, behavior is identical to Step 4 (backward compatible).
4. **`parent_render_id` wiring**: the new `Render` row created by `/refine` has `parent_render_id` set to the ID of the previous successful render.
5. **Frontend "Refine" button**: visible in the scene editor when `scene.current_render_id` is set. Opens a small inline text input for the refinement prompt. Submits to `POST /scenes/{id}/refine`. Long-polls the same `/render-jobs/{render_id}` endpoint.
6. **"Refined from" annotation**: a small text label under the video player showing `refined from: <short hash>` when the current render has a `parent_render_id`.
7. **Agent prompt-construction upgrade**: the agent's `frames`-aware prompt logic (placeholder in Step 4) is upgraded to use the structured `frames` field meaningfully — each frame's `prompt_augmentation` is woven into the per-section prompt rather than concatenated as a prefix.

### Out of scope

- Render history browsing UI (list of all renders for a scene, ability to click back to any). Step 7+.
- "Revert to previous render" button. Out of scope for Step 5; the data model supports it (`parent_render_id` chain), but the UI is deferred.
- Refinement chains longer than one hop in the UI. The data model supports arbitrary chains; the UI only exposes one level of "refine the current render".
- Excalidraw-frozen refinement (refinement always uses the current saved scene state — see Design section).
- Multi-turn agent conversation / persistent agent memory. The agent remains stateless; context is injected inline per call.
- Thumbnail update on refinement. The worker already sets `scene.thumbnail_artifact_key` on preview; this behavior is unchanged.
- Storyboard `SceneCard` thumbnail changes. Thumbnails always reflect `current_render_id`, which is updated to the latest render regardless of whether it was a generate or refine. No special handling needed.

---

## Design

### Key design decisions (resolved)

#### 1. Agent payload shape: structured fields vs. one blob

**Decision: structured fields.**

The agent receives the previous render's context as three separate fields:

```json
{
  "prompt": "...",
  "excalidraw_scene_json": { ... },
  "frames": [ ... ],
  "previous_source_code": "<full python source from previous render>",
  "previous_prompt": "...",
  "refinement_prompt": "make the circle red"
}
```

Rationale: a single `previous_context` blob would force the agent's prompt-construction logic to parse or re-format it. Separate fields let the agent template them cleanly into the system/user message structure. The LLM benefits from explicit labeling ("here is the previous code", "here is what to change") rather than a fused blob.

All three fields are optional. When absent, the agent behaves exactly as in Step 4. This preserves backward compatibility and lets the same endpoint serve both generate and refine paths if desired (though the controller uses separate endpoints for clarity).

#### 2. Excalidraw state at refinement time

**Decision: refinement uses the current saved scene state.**

When the user clicks "Refine", the controller reads the scene's current `excalidraw_scene_json`, `prompt`, and `frames` from the DB (same as `/generate`), then additionally reads the previous render's source from ObjectStore and the previous render's `scene_py_artifact_key` to recover `previous_prompt`.

This means: if the user edited the Excalidraw canvas between renders, those edits are honored in the refinement. The agent sees the current scene state *plus* the previous source as context. This is the most useful behavior — the user can refine both the visual layout and the prompt delta in one step.

The alternative (freeze the Excalidraw state to the previous render's snapshot) would require storing the full `excalidraw_scene_json` on the `Render` row, which is not in the current schema and adds significant storage overhead for a marginal benefit.

#### 3. Cache behavior

**Decision: no special refinement cache. Use the existing content-hash mechanism.**

The `content_hash` is computed from the generated source bytes (as in Step 3/4). A refinement that produces identical source to a previous render (unlikely but possible) will hit the cache and reuse blobs. A refinement with different inputs will produce a different hash and render fresh. No special refinement-aware cache key is needed.

The `parent_render_id` is metadata for the UI lineage display, not a cache key.

#### 4. Frontend UX

**Decision: minimum viable for Step 5.**

- "Refine" button appears next to "Generate" in the scene editor, enabled only when `scene.current_render_id` is set.
- Clicking "Refine" expands an inline text input labeled "What to change?" with a "Submit Refinement" button.
- On submit, the input collapses and the render status indicator shows the same `generating → queued → preview_ready → final_ready` progression as Generate.
- Under the video player, when `render.parent_render_id` is non-null, a small annotation reads: `refined from: <first 8 chars of parent render's content_hash>`.
- History browsing (list of all renders, click to revert) is out of scope.

#### 5. SceneCard thumbnails

**Decision: no change.** Thumbnails always reflect `scene.current_render_id`, which is updated to the latest render (generate or refine) by the worker. The storyboard view always shows the most recent output.

---

### Controller endpoint

```
POST /api/v1/scenes/{scene_id}/refine
  body: { refinement_prompt: str, cli_flags?: dict }
  → 200: { render_id: str, scene_id: str, status: "generating" }
  → 404: scene not found
  → 409: no successful render exists to refine from
```

**Validation:**
- `refinement_prompt` must be non-empty.
- The scene must have at least one `Render` with `status = "final_ready"` or `status = "preview_ready"`. If not, return `409 Conflict` with `{ detail: "No completed render to refine from. Use /generate first." }`.
- The controller resolves the "previous render" as: `SELECT * FROM render WHERE scene_id = ? AND status IN ('final_ready', 'preview_ready') ORDER BY created_at DESC LIMIT 1`. This is the `parent_render_id` target.

**Lifecycle (identical to `/generate` except steps 4b and 4c):**

```
1. Browser → Controller: POST /api/v1/scenes/{scene_id}/refine { refinement_prompt, cli_flags? }
2. Controller (sync, in request handler):
     - ScenesRepository.get(scene_id) → 404 if missing
     - Resolve previous_render = latest successful Render for scene → 409 if none
     - Create Render row: status="generating", scene_id=..., parent_render_id=previous_render.id, cli_flags_json=normalized
     - Dispatch Taskiq task: refine_and_render(render_id, previous_render_id)
     - Return { render_id, scene_id, status: "generating" } immediately
3. Browser: GET /render-jobs/{render_id} (long-poll, existing endpoint — unchanged)

   [meanwhile, in the Taskiq task body:]

4. Worker:
     a. Load Render + Scene + Frames in one read transaction
     b. Load previous_render = RendersRepository.get(previous_render_id)
     c. Read previous source: ObjectStore.get(previous_render.scene_py_artifact_key) → previous_source_code (str)
     d. Read previous prompt: previous_render's scene snapshot is not stored, so recover it from
        Scene.prompt at the time of the previous render — see "Previous prompt recovery" note below.
     e. Build agent payload:
        {
          prompt: scene.prompt,
          excalidraw_scene_json: scene.excalidraw_scene_json,
          frames: [...],
          previous_source_code: previous_source_code,
          previous_prompt: <recovered>,
          refinement_prompt: render.refinement_prompt  (new column — see Schema deltas)
        }
     f. POST {agent_base_url}/api/v1/animation → { source_code, content_hash }
        - on agent error: Render.status="failed", error_message=..., publish event, return
     g. Compute effective_hash = sha256(content_hash + canonical_cli_flags_json)
     h. RendersRepository.find_by_content_hash(effective_hash):
          - hit + blobs exist → reuse: copy keys, status="final_ready", scene.current_render_id=render_id, publish, return
          - miss or drift → continue
     i. ObjectStore.put(render_source_key(effective_hash), source_code.encode())
        Set Render.scene_py_artifact_key=..., status="queued"
     j. Acquire layersense:lock:render:{effective_hash}
     k. Materialize source to /tmp/layersense-renders/{render_id}/scene.py
     l. Run Manim preview → ObjectStore.put_stream(render_preview_key)
        Render.preview_artifact_key=..., status="preview_ready", publish event
     m. Run Manim final → ObjectStore.put_stream(render_final_key)
        Render.final_artifact_key=..., status="final_ready", publish event
     n. Capture first frame as PNG → ObjectStore.put(thumbnail key)
        Scene.thumbnail_artifact_key=...
     o. Scene.current_render_id=render_id
     p. Release lock, clean up /tmp workdir
5. Browser: long-poll resolves, fetches /artifacts/by-hash/{content_hash}/final
```

**Previous prompt recovery note:** The `Render` row does not store a snapshot of `scene.prompt` at render time (the schema has no such column). For Step 5, the controller passes `scene.prompt` (current value) as `previous_prompt`. This is a pragmatic approximation: if the user edited the prompt between renders, `previous_prompt` will reflect the current prompt, not the one used for the previous render. This is acceptable for Step 5 — the agent uses it as soft context, not a hard constraint. A `Render.prompt_snapshot TEXT` column can be added in a later step if the approximation proves harmful. See Assumptions.

---

### Schema deltas

One new column on `Render`:

```sql
ALTER TABLE render ADD COLUMN refinement_prompt TEXT;
```

Migration: `0004_add_render_refinement_prompt.py`.

`parent_render_id` already exists in the Step 2 schema (`FK Render NULL (SET NULL)`). No change needed.

No other schema changes.

---

### Agent contract extension

`POST /api/v1/animation` request schema gains three optional fields:

```python
class AnimationRequest(BaseModel):
    prompt: str
    excalidraw_scene_json: dict
    frames: list[FramePayload] = []
    # New in Step 5 — all optional; absent = fresh generation (Step 4 behavior)
    previous_source_code: str | None = None
    previous_prompt: str | None = None
    refinement_prompt: str | None = None
```

Response schema is unchanged: `{ source_code: str, content_hash: str }`.

**Agent prompt-construction logic (upgraded in this step):**

The agent's `build_prompt` function (or equivalent) is upgraded from the Step 4 placeholder (concatenated `prompt_augmentation` strings) to:

1. **System message**: role description + Manim coding conventions.
2. **User message — scene description block**: structured per-frame sections using `frame.prompt_augmentation` as the per-section instruction. Each frame maps to one `with self.voiceover(...)` / section block in `construct()`.
3. **User message — refinement context block** (only when `previous_source_code` is present):
   ```
   ## Previous render
   The following Manim source was generated from a previous version of this scene.
   Use it as a starting point. Preserve what works; apply the refinement instruction below.

   ```python
   {previous_source_code}
   ```

   ## Refinement instruction
   {refinement_prompt}
   ```
4. The `previous_prompt` field is included as a brief note ("Previous prompt: ...") before the previous source block, giving the LLM context on what the previous generation was trying to achieve.

This upgrade is backward compatible: when `previous_source_code` is `None`, the refinement context block is omitted entirely and the agent behaves as in Step 4.

---

### `AgentClient` extension

`layersense_controller/src/layersense_controller/services/agent_client.py` gains optional parameters:

```python
def generate_animation(
    self,
    *,
    prompt: str,
    excalidraw_scene_json: dict,
    frames: list[FramePayload],
    previous_source_code: str | None = None,
    previous_prompt: str | None = None,
    refinement_prompt: str | None = None,
) -> AgentResponse:
    ...
```

When the optional fields are `None`, they are omitted from the JSON body (not sent as `null`). The agent's Pydantic model defaults them to `None` on the receiving end — no change to the agent's validation behavior.

---

### Frontend changes

**`SceneEditorRoute.tsx`:**

- "Refine" button added next to "Generate". Disabled when `scene.current_render_id` is `null` or when `isSaving` is true.
- Clicking "Refine" toggles a `showRefineInput` state, revealing an inline `<textarea>` labeled "What to change?" and a "Submit Refinement" button.
- On submit: `POST /api/v1/scenes/{id}/refine { refinement_prompt }` → receive `render_id` → start long-polling via existing `useRenderJob`.
- The refinement input collapses after submit; the render status indicator takes over.
- "Generate" and "Refine" are mutually exclusive while a render is in flight (both disabled).

**`VideoPlayer.tsx` (or its parent):**

- When `currentRender.parent_render_id` is non-null, render a small annotation below the video:
  `refined from: {currentRender.parent_content_hash.slice(0, 8)}` (requires the render-job long-poll response to include `parent_render_id` and `parent_content_hash` — see API response shape below).

**`api.ts`:**

- Add `refineScene(sceneId: string, refinementPrompt: string, cliFlagsJson?: object): Promise<RenderJobStart>`.

**`types.ts`:**

- `RenderJob` gains `parent_render_id: string | null` and `parent_content_hash: string | null`.

**`useRenderJob.ts`:**

- No changes needed beyond the `types.ts` extension. The long-poll endpoint already returns the full render-job state; the new fields are additive.

**Render-job long-poll response extension:**

The controller's `GET /render-jobs/{render_id}` response gains two fields:

```json
{
  "render_id": "...",
  "status": "final_ready",
  "content_hash": "...",
  "parent_render_id": "uuid-or-null",
  "parent_content_hash": "sha256-hex-or-null"
}
```

`parent_content_hash` is resolved by the controller from `RendersRepository.get(parent_render_id).content_hash` when `parent_render_id` is non-null. This avoids a second client-side fetch.

---

### Refinement chain semantics

- A `Render` row with `parent_render_id = null` is a **root render** (produced by `/generate`).
- A `Render` row with `parent_render_id = <id>` is a **refinement render** (produced by `/refine`).
- Chains are linear in the UI (one level of "refined from" annotation). The data model supports arbitrary depth; the UI does not expose it in Step 5.
- `scene.current_render_id` always points at the most recently completed render, regardless of whether it was a generate or refine. The storyboard thumbnail reflects this.
- If a refinement fails, `scene.current_render_id` is not updated. The previous successful render remains current.
- `parent_render_id` uses `SET NULL` on delete (per Step 2 schema). If the parent render row is deleted, the child render's `parent_render_id` becomes `null`. The "refined from" annotation disappears gracefully.

---

## File-level changes

### New (controller)

- `layersense_controller/src/layersense_controller/api/refine.py` — `POST /api/v1/scenes/{scene_id}/refine` router.
- `layersense_controller/src/layersense_controller/render_tasks_refine.py` — `refine_and_render` Taskiq task. (Or fold into `render_tasks_generate.py` as a shared internal function if the two tasks share >80% of their body — see Risks.)
- `layersense_controller/tests/integration/test_refine_api.py`
- `layersense_controller/tests/unit/test_refine_task.py`

### Modified (controller)

- `layersense_controller/src/layersense_controller/main.py` — register `refine` router.
- `layersense_controller/src/layersense_controller/services/agent_client.py` — add optional `previous_source_code`, `previous_prompt`, `refinement_prompt` params to `generate_animation`.
- `layersense_controller/src/layersense_controller/router.py` — extend render-job response schema with `parent_render_id`, `parent_content_hash`.
- `layersense_persistence/src/layersense_persistence/migrations/versions/0004_add_render_refinement_prompt.py` — add `render.refinement_prompt TEXT`.
- `layersense_persistence/src/layersense_persistence/models.py` — add `refinement_prompt: str | None` to `Render`.
- `layersense_persistence/src/layersense_persistence/schemas.py` — add `refinement_prompt` to `RenderSchema`.
- `layersense_controller/tests/integration/test_generate_api.py` — minor: assert `parent_render_id` is null on generate renders.

### Modified (agent)

- `layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py` — add optional `previous_source_code`, `previous_prompt`, `refinement_prompt` to `AnimationRequest`.
- `layersense_agent/src/layersense_agent/services/prompt_builder.py` (or equivalent) — upgrade `frames`-aware prompt construction; add refinement context block when `previous_source_code` is present.
- `layersense_agent/tests/integration/test_animation_api.py` — add VCR-backed test for the refinement path; cassette refresh for the frames-aware prompt upgrade.
- `layersense_agent/tests/integration/test_animation_api_with_mocked_agent_runner.py` — add unit-level test for refinement payload routing.

### Modified (frontend)

- `src/routes/SceneEditorRoute.tsx` — "Refine" button + inline refinement input.
- `src/api.ts` — add `refineScene`.
- `src/types.ts` — extend `RenderJob` with `parent_render_id`, `parent_content_hash`.
- `src/components/VideoPlayer.tsx` (or parent) — "refined from" annotation.
- `src/hooks/useRenderJob.ts` — minor: surface `parent_render_id` / `parent_content_hash` from poll response.
- `*.test.tsx` / `*.test.ts` for each modified component/hook.

### Deleted

Nothing deleted in this step.

### Modified (docs)

- `README.md` — add "Refinement" subsection under "Current Architecture" describing the `/refine` endpoint and `parent_render_id` chain.
- `docs/ROADMAP.md` — mark Step 5 in progress / complete.

---

## Test plan

### Controller (integration, `TestClient(app)` + `fakeredis` + in-memory SQLite + `LocalFSObjectStore(tmp_path)`)

**`test_refine_api.py`:**

- **Happy path**: create scene, generate a render (mock agent via `respx`), then call `POST /scenes/{id}/refine { refinement_prompt: "make it red" }`. Assert:
  - Returns `{ render_id, scene_id, status: "generating" }` immediately.
  - New `Render` row has `parent_render_id` = previous render's ID.
  - `Render.refinement_prompt` = "make it red".
  - Agent was called with `previous_source_code` populated (verified via `respx` request capture).
  - Long-poll eventually reaches `final_ready`.
  - `scene.current_render_id` updated to the new render.
- **409 when no prior render**: call `/refine` on a scene with no completed renders. Assert 409 with descriptive message.
- **404 on unknown scene**: assert 404.
- **Empty refinement_prompt**: assert 422 validation error.
- **Agent failure on refinement**: mocked agent returns 500. Assert `Render.status = "failed"`, `error_message` populated, `scene.current_render_id` unchanged (still points at previous render).
- **Cache hit on refinement**: mock agent returns source identical to a previous render's source. Assert no Manim invocation; status goes straight to `final_ready`; `parent_render_id` still set on the new Render row.
- **Refinement of a refinement (chain depth 2)**: generate → refine → refine again. Assert `parent_render_id` on the third render points at the second. Assert `scene.current_render_id` = third render.
- **Render-job long-poll response includes `parent_render_id` and `parent_content_hash`**: after a refinement render completes, `GET /render-jobs/{render_id}` returns both fields non-null.

**`test_refine_task.py` (unit):**

- `refine_and_render` task reads `previous_source_code` from ObjectStore and passes it to `AgentClient.generate_animation`.
- If `ObjectStore.get(previous_render.scene_py_artifact_key)` raises `ObjectNotFoundError`, task sets `Render.status = "failed"` with a descriptive error message.
- Task does not update `scene.current_render_id` when it fails.

**`test_agent_client.py` (unit, existing file — extend):**

- `generate_animation` with `previous_source_code` present: request body includes all three refinement fields.
- `generate_animation` with `previous_source_code = None`: request body omits the three refinement fields entirely (not sent as `null`).

### Agent (integration)

**`test_animation_api_with_mocked_agent_runner.py` (extend):**

- `POST /api/v1/animation` with `previous_source_code`, `previous_prompt`, `refinement_prompt` present: assert the LLM runner receives a prompt that includes the previous source block and the refinement instruction. Verified by capturing the `Runner.run` call args.
- `POST /api/v1/animation` without refinement fields: behavior identical to Step 4 (no regression).

**`test_animation_api.py` (VCR-backed, extend):**

- New cassette: refinement path with a real previous source and a short refinement prompt. Assert `source_code` in response is non-empty and `content_hash` matches `sha256(source_code.encode()).hexdigest()`.
- Cassette refresh required for the frames-aware prompt upgrade (prompt structure changed).

**Markers:** `integration` for all agent tests; `ai` for the VCR-backed cassette tests.

### Frontend (vitest)

- `SceneEditorRoute`: "Refine" button is hidden when `scene.current_render_id` is null; visible when set.
- `SceneEditorRoute`: clicking "Refine" shows the refinement input; submitting calls `api.refineScene` with the correct args; input collapses after submit.
- `SceneEditorRoute`: "Generate" and "Refine" are both disabled while a render is in flight.
- `VideoPlayer` (or parent): renders "refined from: <short hash>" annotation when `parent_render_id` is non-null; renders nothing when null.
- `useRenderJob`: surfaces `parent_render_id` and `parent_content_hash` from poll response.
- No test mocks `localhost:8000` (agent). All mocks target the controller.

### e2e

**`tests/e2e/test_dev_stack_e2e.py` (extend):**

- Full refinement flow: create project → create scene → PATCH excalidraw + prompt → `POST /scenes/{id}/generate` → long-poll until `final_ready` → `POST /scenes/{id}/refine { refinement_prompt: "make the background black" }` → long-poll until `final_ready` → assert:
  - New render's `parent_render_id` = previous render's ID.
  - `scene.current_render_id` = new render's ID.
  - `/artifacts/by-hash/{new_content_hash}/final` returns 200 with non-empty body.
  - `GET /render-jobs/{new_render_id}` includes `parent_content_hash` non-null.

---

## Acceptance criteria

1. `grep -rn "POST.*refine" layersense_controller/src/` matches exactly one route definition.
2. `grep -rn "parent_render_id" layersense_controller/src/ layersense_persistence/src/` returns matches in: `models.py`, `schemas.py`, the migration file, `refine.py` router, and the refine task. No other files.
3. `grep -rn "previous_source_code" layersense_agent/src/` returns matches in `animate_scene.py` and the prompt-builder module. No other agent files.
4. `grep -rn "refineScene\|/refine" layersense_frontend/src/` returns matches in `api.ts` and `SceneEditorRoute.tsx` only.
5. `grep -rn "localhost:8000\|http://agent" layersense_frontend/src/` returns no matches (browser still only talks to controller — unchanged from Step 4).
6. `uv run --all-packages pytest -m unit` passes.
7. `uv run --all-packages pytest -m integration` passes; coverage for `layersense_controller/src/layersense_controller/api/refine.py` ≥ 95%; `render_tasks_refine.py` ≥ 90%.
8. `npm test` (vitest) passes; new/modified frontend components ≥ 90% covered.
9. `just e2e` passes against the local Docker stack with the extended e2e test.
10. `just test-e2e` passes.
11. `just lint` passes (Python + ESLint).
12. A `Render` row produced by `/refine` has `parent_render_id` non-null. A `Render` row produced by `/generate` has `parent_render_id` null. Verified by the integration tests.
13. If the previous render's source blob is missing from ObjectStore, `/refine` produces a `Render` with `status = "failed"` and a descriptive `error_message`. Verified by a dedicated integration test.
14. The agent's `AnimationRequest` Pydantic model has `previous_source_code`, `previous_prompt`, `refinement_prompt` as optional fields with `None` defaults. Verified by AST/grep on the model definition.
15. `GET /render-jobs/{render_id}` response includes `parent_render_id` and `parent_content_hash` fields. Verified by the integration test asserting the long-poll response shape.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `generate_and_render` and `refine_and_render` tasks share ~80% of their body, leading to duplication | Extract a shared `_run_render_pipeline(render_id, agent_payload)` internal function. Both tasks call it after assembling their respective payloads. Keeps each task thin (~30 LOC) and the shared logic tested once. |
| Previous source blob missing from ObjectStore (e.g., storage wiped between generate and refine) | Task catches `ObjectNotFoundError` from `ObjectStore.get`, sets `Render.status = "failed"` with message "Previous render source not found in object store. Try generating from scratch.", does not update `scene.current_render_id`. Covered by a dedicated integration test. |
| `previous_prompt` approximation (using current `scene.prompt` instead of the prompt at render time) misleads the LLM | Acceptable for Step 5. If it causes visible quality degradation, add `Render.prompt_snapshot TEXT` in a follow-up migration. Surfaced explicitly in Assumptions. |
| Refinement of a failed render (user clicks "Refine" before the 409 guard is tight) | The 409 guard checks `status IN ('final_ready', 'preview_ready')`. A `failed` render does not qualify. The "Refine" button is disabled in the frontend when `scene.current_render_id` is null, but the server-side guard is the authoritative check. |
| Long-poll response shape change (`parent_render_id`, `parent_content_hash`) breaks existing frontend code | Fields are additive. Existing frontend code ignores unknown fields. The `types.ts` extension is backward compatible. |
| Cassette churn on agent VCR tests (frames-aware prompt upgrade changes the LLM payload) | One-time cassette refresh via `just test_python_integration_refresh`. Expected; called out in PR description. |
| Refinement chain depth grows unbounded in the DB | No concern for single-user. Each render is a new row; the chain is navigable via `parent_render_id`. No GC needed at this scale. |
| Worker reads `previous_render.scene_py_artifact_key` and the layout must be stable | Canonical key layout is `renders/{content_hash}/source.py` (per the normalized overview). `keys.py` in `layersense_storage` is the single source of truth — callers never hand-format keys. |

---

## Estimated shape

- Controller: ~250 LOC src + ~350 LOC tests
- Agent: ~150 LOC delta (prompt builder upgrade + new request fields) + ~100 LOC tests
- Frontend: ~200 LOC src + ~150 LOC tests
- Persistence migration: ~20 LOC
- Docs: ~40 LOC

Total: ~1260 LOC delta. Single PR is appropriate given the scope.

---

## Assumptions

1. **`previous_prompt` approximation is acceptable.** The controller passes `scene.prompt` (current value) as `previous_prompt` rather than storing a snapshot on the `Render` row. If the user edits the prompt between renders, the `previous_prompt` field will reflect the current prompt, not the one used for the previous render. This is a pragmatic simplification. A `Render.prompt_snapshot` column can be added later if this proves harmful. → **Pushback invited.**

2. **Refinement always uses the current scene state (Excalidraw + prompt + frames).** If the user edited the canvas between renders, those edits are honored. The alternative (freezing the scene state to the previous render's snapshot) requires storing `excalidraw_scene_json` on the `Render` row, which is not in the current schema. → **Pushback invited if frozen-state refinement is preferred.**

3. **"Previous render" is resolved as the latest `final_ready` or `preview_ready` render for the scene.** If the user has multiple renders in history, refinement always chains from the most recent successful one, not from `scene.current_render_id` (which is the same thing in practice, but the query is explicit). → **Pushback invited if a different resolution strategy is preferred.**

4. **No "Revert to previous render" button in Step 5.** The data model supports it; the UI does not expose it. → **Pushback invited if this is a blocker.**

5. **`refine_and_render` is a separate Taskiq task from `generate_and_render`.** They share a common internal pipeline function. If the user prefers a single task with a `is_refinement` flag, that's a minor refactor. → **Pushback invited.**

6. **The render-job long-poll response is extended with `parent_render_id` and `parent_content_hash`.** This is an additive change; existing clients ignore the new fields. → **Confirm this is acceptable before implementing.**

7. **Cassette refresh on agent VCR tests is acceptable.** The frames-aware prompt upgrade changes the LLM payload structure. → **Confirm before implementing.**

8. **Single PR.** ~1260 LOC delta is manageable in one review. If the agent prompt-builder upgrade is contentious, it can be split into a separate PR (agent-only) that lands first. → **Pushback invited.**

→ Correct any of these or I proceed to implementation. The most consequential open question is assumption (1): whether to store `Render.prompt_snapshot` now (adds one column to the migration, eliminates the approximation) or defer it. If you want the approximation eliminated from day one, say so and I'll add the column to the schema delta.
