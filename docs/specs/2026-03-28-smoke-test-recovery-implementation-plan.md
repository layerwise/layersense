# Smoke Test Recovery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore the local smoke path by aligning the frontend-agent request contract around Excalidraw `scene` and making controller queued renders reach an observable terminal state.

**Architecture:** The agent API becomes the canonical contract boundary for `prompt` plus typed `scene`, with internal JSON serialization for the LLM prompt. The controller keeps its public API but hardens the queued render pipeline so success produces artifacts/events and failures surface as explicit `render_failed` outcomes instead of disappearing.

**Tech Stack:** FastAPI, Pydantic, pytest, Vitest, React, TypeScript, Manim, Docker Compose

---

### Task 1: Agent request contract test

**Files:**
- Modify: `layersense_agent/tests/test_animate_scene.py`

**Step 1: Write the failing test**

Add a test that posts this payload to `/api/v1/animation`:

```python
payload = {
    "prompt": "animate a circle",
    "scene": {"elements": [], "appState": {}, "files": {}},
}
```

Assert:
- status code is `200`
- response contains `conversation_id`
- response contains `scene_path`
- generated scene file exists

**Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_agent/tests/test_animate_scene.py::test_create_animation_writes_file -v`

Expected: FAIL with validation or model mismatch because the agent still expects `json_data`.

**Step 3: Write minimal implementation**

Do not implement yet. This task is only for the red test.

**Step 4: Commit**

Do not commit yet.

### Task 2: Agent typed scene model and endpoint update

**Files:**
- Modify: `layersense_agent/src/layersense_agent/models/base.py`
- Modify: `layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py`
- Test: `layersense_agent/tests/test_animate_scene.py`

**Step 1: Write the minimal model**

Add a permissive Pydantic snapshot model, e.g.:

```python
class ExcalidrawSceneSnapshot(BaseModel):
    elements: list[dict[str, Any]]
    appState: dict[str, Any]
    files: dict[str, Any]

    model_config = {"extra": "ignore"}


class AnimationInputs(BaseModel):
    prompt: str
    scene: ExcalidrawSceneSnapshot
```

Use `extra="ignore"` only where it improves tolerance without weakening the top-level contract.

**Step 2: Update endpoint implementation**

In `animate_scene.py`, replace `inputs.json_data` usage with JSON serialization of `inputs.scene`, e.g.:

```python
scene_json = json.dumps(inputs.scene.model_dump(mode="json"))
user_prompt = inputs.prompt + "\n" + scene_json
```

Keep response shape unchanged.

**Step 3: Strengthen the test**

In `test_animate_scene.py`, assert the mocked runner receives the serialized scene content in its prompt input.

Example assertion shape:

```python
mock_runner.run.assert_awaited_once()
runner_prompt = mock_runner.run.await_args.args[1]
assert '"elements": []' in runner_prompt
```

**Step 4: Run focused tests**

Run: `uv run --all-packages pytest layersense_agent/tests/test_animate_scene.py -v`

Expected: PASS.

**Step 5: Commit**

Do not commit yet unless asked.

### Task 3: Frontend contract regression test review

**Files:**
- Review: `layersense_frontend/src/api.test.ts`
- Review: `layersense_frontend/src/types.ts`

**Step 1: Confirm existing test coverage**

Verify the existing `createAnimation` test already asserts the canonical payload:

```ts
{ prompt: 'animate a circle', scene: { elements: [], appState: {}, files: {} } }
```

**Step 2: Adjust only if needed**

If the frontend types no longer align with the agent contract expectations, make the smallest type update necessary.

**Step 3: Run focused frontend tests**

Run: `bun run --cwd layersense_frontend test -- --run src/api.test.ts`

Expected: PASS.

**Step 4: Commit**

Do not commit yet.

### Task 4: Controller queued render failure reproduction test

**Files:**
- Modify: `layersense_controller/tests/test_router.py`

**Step 1: Write a failing queued-render success test**

Add a test that:
- creates a real scene file in `tmp_path`
- monkeypatches `settings.artifacts_dir`
- monkeypatches `render_preview` and `render_final` to create artifact files in the configured cache paths
- monkeypatches `manager.broadcast` to capture events
- posts to `/render`

Assert eventually, after the request returns:
- response is `200`
- response body is `{"status": "queued"}`
- preview/final events were broadcast
- artifact target files exist

**Step 2: Run the test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py::test_render_queued_job_broadcasts_terminal_events -v`

Expected: FAIL, exposing the current orchestration gap.

**Step 3: Write a failing unexpected-error test**

Add a second test that makes `render_preview` or `render_final` raise a non-`RenderError` exception and asserts the pipeline still emits `render_failed`.

**Step 4: Run the second test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py::test_render_queued_job_broadcasts_failure_for_unexpected_exception -v`

Expected: FAIL.

### Task 5: Controller pipeline hardening

**Files:**
- Modify: `layersense_controller/src/layersense_controller/router.py`
- Review: `layersense_controller/src/layersense_controller/render.py`
- Test: `layersense_controller/tests/test_router.py`

**Step 1: Make pipeline outcomes observable**

Update `_render_pipeline(...)` so it:
- logs render start
- logs preview success and target
- logs final success and target
- catches `RenderError`
- also catches unexpected `Exception`
- broadcasts `render_failed` for both controlled and unexpected failures

For unexpected exceptions, preserve useful error text in the payload.

**Step 2: Keep implementation minimal**

Do not redesign the render API. Keep the existing broadcast event shapes.

**Step 3: Run focused controller tests**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py -v`

Expected: PASS.

**Step 4: Optional focused smoke probe**

If tests pass, verify against the live stack with a known-good scene:

Run: `curl -i -X POST "http://localhost:8001/render" -H "Content-Type: application/json" --data '{"scene_path":"/scenes/generated_smoke.py","conversation_id":"smoke"}'`

Expected: `200` with `{"status":"queued"}`, followed by artifact files appearing in `layersense_artifacts/` or a visible `render_failed` event/log.

### Task 6: Documentation alignment

**Files:**
- Modify: `README.md`
- Review: `docs/ROADMAP.md`
- Review: `docs/plans/2026-03-16-frontend-stock-excalidraw-integration-plan.md`

**Step 1: Update public-facing contract docs**

Make sure the README and any immediately relevant docs describe the canonical agent payload as structured Excalidraw `scene`, not `json_data`.

**Step 2: Keep edits minimal**

Only update docs that are now stale because of this contract clarification.

**Step 3: No speculative docs work**

Do not rewrite historical plan docs beyond minimal clarifying notes if needed.

### Task 7: Verify whole change set

**Files:**
- Verify only

**Step 1: Run agent tests**

Run: `uv run --all-packages pytest layersense_agent/tests/test_animate_scene.py -v`

Expected: PASS.

**Step 2: Run controller tests**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py -v`

Expected: PASS.

**Step 3: Run frontend API test**

Run: `bun run --cwd layersense_frontend test -- --run src/api.test.ts`

Expected: PASS.

**Step 4: Run required repo verification**

Run: `just lint`

Expected: exit `0`.

**Step 5: Run required repo verification**

Run: `just test`

Expected: exit `0`.

### Task 8: Live smoke re-check

**Files:**
- Verify only

**Step 1: Reload the browser app**

Open `http://localhost:3000`.

**Step 2: Trigger generate**

Use a simple prompt and default empty or near-empty scene.

**Step 3: Verify contract no longer fails**

Expected: no `422` from `/api/v1/animation`.

**Step 4: Verify render reaches terminal state**

Expected: preview/final artifact URLs appear in the UI, or a concrete `render_failed` message appears instead of silent queueing.
