# Excalidraw Model Specificity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the live raw Excalidraw scene passthrough with a typed normalized scene contract while preserving current generate -> Python scene file behavior.

**Architecture:** Keep the frontend request shape stable, but normalize scene payloads immediately inside `layersense_agent` into a typed internal IR. The endpoint should depend on a normalization service plus typed models instead of broad `dict[str, Any]` scene structures.

**Tech Stack:** FastAPI, Pydantic v2, pytest, TypeScript, Excalidraw frontend types

---

### Task 1: Define the normalized backend scene contract

**Files:**
- Modify: `layersense_agent/src/layersense_agent/models/scene.py`
- Test: `layersense_agent/tests/unit/test_scene_models.py`

- [ ] **Step 1: Write the failing test**

```python
from pydantic import ValidationError
import pytest

from layersense_agent.models.scene import NormalizedScene


def test_normalized_scene_accepts_rectangle_ellipse_and_freedraw() -> None:
    payload = {
        "elements": [
            {
                "id": "rect-1",
                "type": "rectangle",
                "x": 10,
                "y": 20,
                "width": 100,
                "height": 50,
                "angle": 0,
                "strokeColor": "#000000",
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 2,
                "strokeStyle": "solid",
                "opacity": 100,
            },
            {
                "id": "ellipse-1",
                "type": "ellipse",
                "x": 0,
                "y": 0,
                "width": 80,
                "height": 80,
                "angle": 0,
                "strokeColor": "#ff0000",
                "backgroundColor": "#ffffff",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "solid",
                "opacity": 100,
            },
            {
                "id": "path-1",
                "type": "freedraw",
                "x": 0,
                "y": 0,
                "width": 10,
                "height": 10,
                "angle": 0,
                "strokeColor": "#000000",
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "solid",
                "opacity": 100,
                "points": [[0, 0], [1, 1]],
            },
        ],
        "appState": {"viewBackgroundColor": "#ffffff"},
        "files": {},
    }

    scene = NormalizedScene.model_validate(payload)

    assert len(scene.elements) == 3
    assert scene.appState.viewBackgroundColor == "#ffffff"


def test_freedraw_requires_points() -> None:
    payload = {
        "elements": [
            {
                "id": "path-1",
                "type": "freedraw",
                "x": 0,
                "y": 0,
                "width": 10,
                "height": 10,
                "angle": 0,
                "strokeColor": "#000000",
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "solid",
                "opacity": 100,
            }
        ],
        "appState": {},
        "files": {},
    }

    with pytest.raises(ValidationError):
        NormalizedScene.model_validate(payload)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_scene_models.py -q`
Expected: FAIL because `NormalizedScene` and typed variants do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

HexColor = Annotated[
    str,
    StringConstraints(pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"),
]


class BaseElement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    x: int
    y: int
    width: int
    height: int
    angle: float
    strokeColor: HexColor
    backgroundColor: str
    fillStyle: str
    strokeWidth: int
    strokeStyle: str
    opacity: float


class RectangleElement(BaseElement):
    type: Literal["rectangle"]


class EllipseElement(BaseElement):
    type: Literal["ellipse"]


class FreedrawElement(BaseElement):
    type: Literal["freedraw"]
    points: list[list[float]]


NormalizedElement = Annotated[
    RectangleElement | EllipseElement | FreedrawElement,
    Field(discriminator="type"),
]


class NormalizedAppState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    viewBackgroundColor: HexColor | None = None


class NormalizedScene(BaseModel):
    elements: list[NormalizedElement]
    appState: NormalizedAppState
    files: dict[str, object]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_scene_models.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_agent/src/layersense_agent/models/scene.py layersense_agent/tests/unit/test_scene_models.py
git commit -m "feat(agent): add normalized excalidraw scene models"
```

### Task 2: Add a scene normalization service

**Files:**
- Create: `layersense_agent/src/layersense_agent/services/scene_normalizer.py`
- Test: `layersense_agent/tests/unit/test_scene_normalizer.py`

- [ ] **Step 1: Write the failing test**

```python
from layersense_agent.services.scene_normalizer import normalize_scene


def test_normalize_scene_filters_deleted_elements() -> None:
    payload = {
        "elements": [
            {
                "id": "deleted-1",
                "type": "rectangle",
                "x": 0,
                "y": 0,
                "width": 10,
                "height": 10,
                "angle": 0,
                "strokeColor": "#000000",
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "solid",
                "opacity": 100,
                "isDeleted": True,
            },
            {
                "id": "live-1",
                "type": "rectangle",
                "x": 5,
                "y": 5,
                "width": 20,
                "height": 20,
                "angle": 0,
                "strokeColor": "#000000",
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "solid",
                "opacity": 100,
            },
        ],
        "appState": {},
        "files": {},
    }

    scene = normalize_scene(payload)

    assert len(scene.elements) == 1
    assert scene.elements[0].id == "live-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_scene_normalizer.py -q`
Expected: FAIL because `normalize_scene` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
from typing import Any

from layersense_agent.models.scene import NormalizedScene


def normalize_scene(payload: dict[str, Any]) -> NormalizedScene:
    filtered_elements = [
        element
        for element in payload.get("elements", [])
        if isinstance(element, dict) and not element.get("isDeleted", False)
    ]
    normalized_payload = {
        "elements": filtered_elements,
        "appState": payload.get("appState", {}),
        "files": payload.get("files", {}),
    }
    return NormalizedScene.model_validate(normalized_payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_scene_normalizer.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_agent/src/layersense_agent/services/scene_normalizer.py layersense_agent/tests/unit/test_scene_normalizer.py
git commit -m "feat(agent): normalize incoming excalidraw scenes"
```

### Task 3: Wire normalization into the animation endpoint

**Files:**
- Modify: `layersense_agent/src/layersense_agent/models/base.py`
- Modify: `layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py`
- Modify: `layersense_agent/tests/unit/test_animate_scene.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import patch


def test_create_animation_normalizes_scene_before_generation(client):
    c, _, mock_runner = client
    payload = {
        "prompt": "animate a circle",
        "scene": {
            "elements": [
                {
                    "id": "shape-1",
                    "type": "rectangle",
                    "x": 0,
                    "y": 0,
                    "width": 10,
                    "height": 10,
                    "angle": 0,
                    "strokeColor": "#000000",
                    "backgroundColor": "transparent",
                    "fillStyle": "solid",
                    "strokeWidth": 1,
                    "strokeStyle": "solid",
                    "opacity": 100,
                }
            ],
            "appState": {},
            "files": {},
        },
    }

    with patch("layersense_agent.api.v1.endpoints.animate_scene.normalize_scene") as normalize_mock:
        normalize_mock.return_value.model_dump_json.return_value = '{"elements":[],"appState":{},"files":{}}'

        response = c.post("/api/v1/animation", json=payload)

    assert response.status_code == 200
    normalize_mock.assert_called_once_with(payload["scene"])
    runner_prompt = mock_runner.run.await_args.args[1]
    assert '{"elements":[],"appState":{},"files":{}}' in runner_prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_animate_scene.py -q`
Expected: FAIL because the endpoint still serializes the raw request scene directly.

- [ ] **Step 3: Write minimal implementation**

```python
from layersense_agent.services.scene_normalizer import normalize_scene


normalized_scene = normalize_scene(inputs.scene)
scene_json = normalized_scene.model_dump_json()
user_prompt = inputs.prompt + "\n" + scene_json
```

And update `AnimationInputs` so `scene` can enter as a raw mapping suitable for normalization:

```python
class AnimationInputs(BaseModel):
    prompt: str = Field(description="The prompt for the animation.")
    scene: dict[str, Any] = Field(description="The Excalidraw scene snapshot for the animation.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_animate_scene.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_agent/src/layersense_agent/models/base.py layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py layersense_agent/tests/unit/test_animate_scene.py
git commit -m "feat(agent): normalize scene payloads before generation"
```

### Task 4: Tighten frontend scene typings without behavior changes

**Files:**
- Modify: `layersense_frontend/src/types.ts`
- Modify: `layersense_frontend/src/components/Canvas.tsx`
- Test: `layersense_frontend/src/components/Canvas.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, expect, it } from 'vitest'
import type { ExcalidrawSceneSnapshot } from '../types'

describe('ExcalidrawSceneSnapshot typing', () => {
  it('accepts a typed snapshot shape', () => {
    const snapshot: ExcalidrawSceneSnapshot = {
      elements: [],
      appState: {},
      files: {},
    }

    expect(snapshot.elements).toEqual([])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run --cwd layersense_frontend test -- --run Canvas.test.tsx`
Expected: FAIL or typecheck issue once the snapshot type is narrowed from `unknown[]`.

- [ ] **Step 3: Write minimal implementation**

```ts
import type {
  AppState,
  BinaryFiles,
  ExcalidrawElement,
} from '@excalidraw/excalidraw/types'

export type ExcalidrawSceneSnapshot = {
  elements: readonly ExcalidrawElement[]
  appState: Partial<AppState>
  files: BinaryFiles
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run --cwd layersense_frontend test -- --run Canvas.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_frontend/src/types.ts layersense_frontend/src/components/Canvas.tsx layersense_frontend/src/components/Canvas.test.tsx
git commit -m "chore(frontend): tighten excalidraw scene typings"
```

### Task 5: Verify the stage and align docs

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Update docs to reflect the normalized scene boundary**

```md
- `layersense_agent/` now normalizes Excalidraw payloads into a typed internal scene model before prompt construction.
```

- [ ] **Step 2: Run focused tests**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_scene_models.py layersense_agent/tests/unit/test_scene_normalizer.py layersense_agent/tests/unit/test_animate_scene.py -q`
Expected: PASS

Run: `bun run --cwd layersense_frontend test -- --run Canvas.test.tsx`
Expected: PASS

- [ ] **Step 3: Run repo verification**

Run: `just lint`
Expected: PASS

Run: `just test`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add README.md docs/ROADMAP.md
git commit -m "docs: describe normalized excalidraw scene contract"
```
