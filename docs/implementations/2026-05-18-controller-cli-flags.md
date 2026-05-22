# Controller CLI Flags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace shared `RenderOptions` with controller-owned `CLIFlags`, remove background color from controller requests, and update the frontend, agent, tests, and docs to the new contract.

**Architecture:** `CLIFlags` becomes a controller-local Pydantic model nested inside `POST /render` request bodies. The agent stops returning controller render settings and remains responsible only for embedding background color into generated scene code. Cache identity and Taskiq payloads continue to include normalized render-job inputs, but now only for supported controller CLI flags.

**Tech Stack:** FastAPI, Pydantic, Taskiq, pytest, Vite/TypeScript, Manim CLI

---

### Task 1: Define the New Controller Contract

**Files:**
- Modify: `layersense_controller/src/layersense_controller/router.py`
- Modify: `layersense_controller/src/layersense_controller/render_tasks.py`
- Test: `layersense_controller/tests/unit/test_router.py`
- Test: `layersense_controller/tests/unit/test_render_tasks.py`

- [ ] **Step 1: Write the failing router test for `cli_flags`**

```python
def test_render_request_accepts_cli_flags_body(client):
    response = client.post(
        "/render",
        json={
            "scene_path": str(scene_path),
            "conversation_id": "conv-123",
            "cli_flags": {"quality": "m", "renderer": "cairo"},
        },
    )
    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/unit/test_router.py::test_render_request_accepts_cli_flags_body -v`
Expected: FAIL because `RenderRequest` still expects `render_options` or does not expose `cli_flags`

- [ ] **Step 3: Add `CLIFlags` and rename controller request plumbing**

```python
class CLIFlags(BaseModel):
    quality: Literal["l", "m", "h", "p", "k"] | None = None
    resolution: Resolution | None = None
    frame_rate: float | None = Field(default=None, gt=0)
    renderer: Literal["cairo", "opengl"] | None = None
    from_animation_number: str | None = None


class RenderRequest(BaseModel):
    scene_path: str
    conversation_id: str
    cli_flags: CLIFlags = Field(default_factory=CLIFlags)
```

- [ ] **Step 4: Update Taskiq payload serialization to `cli_flags`**

```python
def request_cli_flags_payload(cli_flags: CLIFlags) -> dict[str, object]:
    return cli_flags.model_dump(mode="json", exclude_none=True)
```

- [ ] **Step 5: Run focused controller request tests**

Run: `uv run --all-packages pytest layersense_controller/tests/unit/test_router.py layersense_controller/tests/unit/test_render_tasks.py -v`
Expected: PASS for renamed request/task payload behavior

### Task 2: Map Supported CLI Flags to Manim Args

**Files:**
- Modify: `layersense_controller/src/layersense_controller/render.py`
- Test: `layersense_controller/tests/unit/test_render.py`
- Test: `layersense_controller/tests/integration/test_render_paths_and_failures.py`

- [ ] **Step 1: Write the failing unit test for CLI arg mapping**

```python
@pytest.mark.asyncio
async def test_render_preview_passes_quality_and_renderer_flags(tmp_path, monkeypatch):
    await render_preview(scene_path, "abc123", CLIFlags(quality="m", renderer="cairo"))
    assert "-q" in captured_args
    assert "m" in captured_args
    assert "--renderer" in captured_args
    assert "cairo" in captured_args
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/unit/test_render.py::test_render_preview_passes_quality_and_renderer_flags -v`
Expected: FAIL because `render.py` still expects `RenderOptions`

- [ ] **Step 3: Implement minimal CLI flag translation helper**

```python
def _cli_args(cli_flags: CLIFlags | None) -> list[str]:
    if cli_flags is None:
        return []

    args: list[str] = []
    if cli_flags.quality is not None:
        args.extend(["-q", cli_flags.quality])
    if cli_flags.resolution is not None:
        args.extend(["-r", cli_flags.resolution])
    if cli_flags.frame_rate is not None:
        args.extend(["--fps", str(cli_flags.frame_rate)])
    if cli_flags.renderer is not None:
        args.extend(["--renderer", cli_flags.renderer])
    if cli_flags.from_animation_number is not None:
        args.extend(["-n", cli_flags.from_animation_number])
    return args
```

- [ ] **Step 4: Remove background color handling from controller render code**

```python
process = await asyncio.create_subprocess_exec(
    "manim",
    "render",
    "--config_file",
    str(config_path),
    *_cli_args(cli_flags),
    "--media_dir",
    str(media_dir_path),
    ...
)
```

- [ ] **Step 5: Run render unit and integration tests**

Run: `uv run --all-packages pytest layersense_controller/tests/unit/test_render.py layersense_controller/tests/integration/test_render_paths_and_failures.py -v`
Expected: PASS with supported CLI flags and no background-color-specific assertions

### Task 3: Remove Agent Response Coupling

**Files:**
- Modify: `layersense_agent/src/layersense_agent/models/base.py`
- Modify: `layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py`
- Test: `layersense_agent/tests/unit/test_animate_scene.py`
- Test: `layersense_agent/tests/integration/test_animation_api.py`

- [ ] **Step 1: Write the failing test asserting the animation response no longer includes `render_options`**

```python
def test_create_animation_does_not_return_render_options(client):
    response = client.post("/api/v1/animation", json=payload)
    assert "render_options" not in response.json()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_animate_scene.py::test_create_animation_does_not_return_render_options -v`
Expected: FAIL because response model still includes `render_options`

- [ ] **Step 3: Remove `render_options` from the agent response model and endpoint output**

```python
class AnimationCreatedResponse(BaseModel):
    conversation_id: str
    scene_path: str
```
```

- [ ] **Step 4: Keep scene-code background injection intact**

```python
scene_code = apply_render_options_to_scene_code(
    strip_code_fences(result.final_output),
    render_options,
)
```

- [ ] **Step 5: Run focused agent tests**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_animate_scene.py layersense_agent/tests/integration/test_animation_api.py -v --integration-mode=replay`
Expected: PASS without `render_options` in API responses

### Task 4: Update Frontend Contracts and Request Builder

**Files:**
- Modify: `layersense_frontend/src/types.ts`
- Modify: `layersense_frontend/src/api.ts`
- Modify: `layersense_frontend/src/App.tsx`
- Test: relevant frontend test file if present; otherwise rely on `just test`

- [ ] **Step 1: Update TypeScript types to `CLIFlags`**

```ts
export type CLIFlags = {
  quality?: 'l' | 'm' | 'h' | 'p' | 'k'
  resolution?: string
  frame_rate?: number
  renderer?: 'cairo' | 'opengl'
  from_animation_number?: string
}

export type RenderQueueRequest = {
  scene_path: string
  conversation_id: string
  cli_flags: CLIFlags
}
```

- [ ] **Step 2: Remove agent-response `render_options` usage from the frontend flow**

```ts
const animation = await createAnimation(payload)
const renderResponse = await queueRender({
  scene_path: animation.scene_path,
  conversation_id: animation.conversation_id,
  cli_flags: {},
})
```

- [ ] **Step 3: Run frontend validation**

Run: `just test`
Expected: frontend typecheck/tests pass along with Python suite once migration is complete

### Task 5: Update E2E and Cache Identity Expectations

**Files:**
- Modify: `tests/e2e/test_dev_stack_e2e.py`
- Modify: `layersense_controller/src/layersense_controller/cache.py`
- Test: `layersense_controller/tests/unit/test_cache.py`
- Test: `tests/e2e/test_dev_stack_e2e.py`

- [ ] **Step 1: Write the failing cache/e2e expectations for `cli_flags`**

```python
def test_hash_render_request_uses_cli_flags_payload(...):
    payload = {"quality": "m"}
    assert hash_render_request(scene_path, payload) != hash_render_request(scene_path, {})
```

- [ ] **Step 2: Update e2e helpers to use `cli_flags` instead of `render_options`**

```python
def _queue_render(scene_path: str, conversation_id: str, cli_flags: dict[str, Any] | None = None):
    payload = {"scene_path": scene_path, "conversation_id": conversation_id}
    if cli_flags is not None:
        payload["cli_flags"] = cli_flags
```

- [ ] **Step 3: Remove background-color-derived controller expectations from e2e**

```python
render_response = _queue_render(
    animation["scene_path"],
    animation["conversation_id"],
    {},
)
```

- [ ] **Step 4: Add one non-empty supported `cli_flags` e2e path**

```python
cli_flags = {"quality": "m"}
render_response = _queue_render(controller_scene_path, "controller-smoke", cli_flags)
```

- [ ] **Step 5: Run targeted cache and e2e tests**

Run: `uv run --all-packages pytest layersense_controller/tests/unit/test_cache.py -v`
Expected: PASS

Run: `uv run --all-packages pytest tests/e2e/test_dev_stack_e2e.py -m e2e -v`
Expected: PASS against a running stack or the compose-driven `just test-e2e` environment

### Task 6: Update Docs and Final Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-03-07-layersense-architecture-design.md` if it references `render_options`
- Modify: `docs/superpowers/specs/2026-05-04-controller-integration-testing-design.md` if it references `RenderOptions`

- [ ] **Step 1: Update docs to reflect `cli_flags` and agent/controller ownership boundaries**

```md
- agent writes background configuration into generated scene code when present
- frontend queues renders with optional controller `cli_flags`
- controller applies only allowlisted Manim CLI flags from the render request body
```

- [ ] **Step 2: Run full verification**

Run: `just lint`
Expected: PASS

Run: `just test`
Expected: PASS

- [ ] **Step 3: Review diff for scope correctness**

Run: `git diff --stat && git diff -- README.md layersense_controller/src/layersense_controller/router.py layersense_controller/src/layersense_controller/render.py`
Expected: only intended contract, test, and docs changes
