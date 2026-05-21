# Excalidraw Prompt Bypassing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move deterministic Excalidraw-derived render configuration out of the freeform LLM prompt and into explicit render options, starting with background color.

**Architecture:** Use the normalized scene contract from stage 1 as the extraction source. The agent derives a small allowlisted `render_options` structure, excludes those fields from prompt responsibility, and threads the options through the frontend/controller render contract. The controller overlays these options onto its packaged preview/final render defaults and incorporates them into cache identity.

**Tech Stack:** FastAPI, Pydantic v2, pytest, React, TypeScript, Manim controller config pipeline

---

### Task 1: Define the render-options contract

**Files:**
- Modify: `layersense_agent/src/layersense_agent/models/base.py`
- Modify: `layersense_controller/src/layersense_controller/router.py`
- Modify: `layersense_frontend/src/types.ts`
- Test: `layersense_controller/tests/test_router.py`

- [ ] **Step 1: Write the failing test**

```python
from layersense_controller.router import RenderRequest


def test_render_request_accepts_background_color() -> None:
    request = RenderRequest.model_validate(
        {
            "scene_path": "/tmp/generated_123.py",
            "conversation_id": "conversation-123",
            "render_options": {"background_color": "#112233"},
        }
    )

    assert request.render_options.background_color == "#112233"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py -q`
Expected: FAIL because `RenderRequest` has no `render_options` field.

- [ ] **Step 3: Write minimal implementation**

```python
class RenderOptions(BaseModel):
    background_color: str | None = None


class RenderRequest(BaseModel):
    scene_path: str
    conversation_id: str
    render_options: RenderOptions = Field(default_factory=RenderOptions)
```

Mirror the same transport shape in agent/frontend typing.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_agent/src/layersense_agent/models/base.py layersense_controller/src/layersense_controller/router.py layersense_frontend/src/types.ts layersense_controller/tests/test_router.py
git commit -m "feat(render): add render options contract"
```

### Task 2: Extract background color from the normalized scene

**Files:**
- Create: `layersense_agent/src/layersense_agent/services/render_options.py`
- Test: `layersense_agent/tests/unit/test_render_options.py`

- [ ] **Step 1: Write the failing test**

```python
from layersense_agent.models.scene import NormalizedScene
from layersense_agent.services.render_options import extract_render_options


def test_extract_render_options_uses_view_background_color() -> None:
    scene = NormalizedScene.model_validate(
        {
            "elements": [],
            "appState": {"viewBackgroundColor": "#abc123"},
            "files": {},
        }
    )

    options = extract_render_options(scene)

    assert options.background_color == "#abc123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_render_options.py -q`
Expected: FAIL because `extract_render_options` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
from layersense_agent.models.base import RenderOptions
from layersense_agent.models.scene import NormalizedScene


def extract_render_options(scene: NormalizedScene) -> RenderOptions:
    return RenderOptions(background_color=scene.appState.viewBackgroundColor)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_render_options.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_agent/src/layersense_agent/services/render_options.py layersense_agent/tests/unit/test_render_options.py
git commit -m "feat(agent): extract render options from normalized scene"
```

### Task 3: Thread render options through the agent and frontend handoff

**Files:**
- Modify: `layersense_agent/src/layersense_agent/models/base.py`
- Modify: `layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py`
- Modify: `layersense_frontend/src/App.tsx`
- Modify: `layersense_frontend/src/types.ts`
- Modify: `layersense_agent/tests/unit/test_animate_scene.py`

- [ ] **Step 1: Write the failing test**

```python
def test_create_animation_returns_render_options(client):
    c, _, _ = client
    payload = {
        "prompt": "animate a circle",
        "scene": {
            "elements": [],
            "appState": {"viewBackgroundColor": "#334455"},
            "files": {},
        },
    }

    response = c.post("/api/v1/animation", json=payload)

    assert response.status_code == 200
    assert response.json()["render_options"]["background_color"] == "#334455"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_animate_scene.py -q`
Expected: FAIL because the response does not include render options.

- [ ] **Step 3: Write minimal implementation**

```python
normalized_scene = normalize_scene(inputs.scene)
render_options = extract_render_options(normalized_scene)

return AnimationCreatedResponse(
    conversation_id=conversation_id,
    scene_path=str(scene_path),
    render_options=render_options,
)
```

And in the frontend queue call:

```ts
await queueRender({
  scene_path: animation.scene_path,
  conversation_id: animation.conversation_id,
  render_options: animation.render_options,
})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_animate_scene.py -q`
Expected: PASS

Run: `npm --prefix layersense_frontend test -- --run App.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_agent/src/layersense_agent/models/base.py layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py layersense_frontend/src/App.tsx layersense_frontend/src/types.ts layersense_agent/tests/unit/test_animate_scene.py
git commit -m "feat(flow): pass render options from agent to controller"
```

### Task 4: Apply render options in controller render execution

**Files:**
- Modify: `layersense_controller/src/layersense_controller/render.py`
- Test: `layersense_controller/tests/test_render.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from layersense_controller.models import RenderOptions
from layersense_controller.render import render_preview


@pytest.mark.asyncio
async def test_render_preview_passes_background_override(tmp_path: Path) -> None:
    scene_path = tmp_path / "generated_123.py"
    scene_path.write_text("class GeneratedScene: pass")

    with patch("layersense_controller.render.asyncio.create_subprocess_exec", new=AsyncMock()) as create_exec:
        try:
            await render_preview(scene_path, "hash-123", RenderOptions(background_color="#ffffff"))
        except Exception:
            pass

    args = create_exec.await_args.args
    assert "--background_color" in args
    assert "#ffffff" in args
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/test_render.py -q`
Expected: FAIL because render functions do not accept render options.

- [ ] **Step 3: Write minimal implementation**

```python
async def _run_manim(scene_path: Path, render_kind: str, render_options: RenderOptions) -> Path:
    extra_args: list[str] = []
    if render_options.background_color:
        extra_args.extend(["--background_color", render_options.background_color])

    process = await asyncio.create_subprocess_exec(
        "manim",
        "render",
        "--config_file",
        str(config_path),
        *extra_args,
        "--media_dir",
        str(media_dir_path),
        ...
    )


async def render_preview(scene_path: Path, content_hash: str, render_options: RenderOptions) -> Path:
    return await _run_manim(scene_path, "preview", render_options)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/test_render.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_controller/src/layersense_controller/render.py layersense_controller/tests/test_render.py
git commit -m "feat(controller): apply render option overrides to manim"
```

### Task 5: Include render options in cache identity

**Files:**
- Modify: `layersense_controller/src/layersense_controller/router.py`
- Modify: `layersense_controller/src/layersense_controller/cache.py`
- Test: `layersense_controller/tests/test_router.py`

- [ ] **Step 1: Write the failing test**

```python
def test_render_cache_key_changes_when_background_changes(client, tmp_path):
    scene_path = tmp_path / "generated_123.py"
    scene_path.write_text("from manim import Scene\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n")

    first = client.post(
        "/render",
        json={
            "scene_path": str(scene_path),
            "conversation_id": "conversation-1",
            "render_options": {"background_color": "#000000"},
        },
    )
    second = client.post(
        "/render",
        json={
            "scene_path": str(scene_path),
            "conversation_id": "conversation-2",
            "render_options": {"background_color": "#ffffff"},
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"status": "queued"}
    assert second.json() == {"status": "queued"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py -q`
Expected: FAIL because cache identity is based only on scene file content.

- [ ] **Step 3: Write minimal implementation**

```python
import hashlib
import json


def hash_render_request(scene_path: Path, render_options: RenderOptions) -> str:
    file_hash = hash_file(scene_path)
    render_options_json = json.dumps(render_options.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(f"{file_hash}:{render_options_json}".encode()).hexdigest()
```

Use that request hash in router cache lookups/stores instead of raw file hash where artifact identity is determined.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/test_router.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_controller/src/layersense_controller/router.py layersense_controller/src/layersense_controller/cache.py layersense_controller/tests/test_router.py
git commit -m "fix(cache): include render options in artifact identity"
```

### Task 6: Verify the stage and align docs

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Update docs to describe render-option bypassing**

```md
- The agent now extracts allowlisted render options, including Excalidraw background color, and passes them explicitly to the controller render job.
```

- [ ] **Step 2: Run focused tests**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_render_options.py layersense_agent/tests/unit/test_animate_scene.py layersense_controller/tests/test_router.py layersense_controller/tests/test_render.py -q`
Expected: PASS

Run: `npm --prefix layersense_frontend test -- --run App.test.tsx`
Expected: PASS

- [ ] **Step 3: Run repo verification**

Run: `just lint`
Expected: PASS

Run: `just test`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add README.md docs/ROADMAP.md
git commit -m "docs: describe excalidraw render option bypassing"
```
