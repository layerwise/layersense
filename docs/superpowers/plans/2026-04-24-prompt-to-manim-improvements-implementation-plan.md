# Prompt-To-Manim Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the current prompt-to-Manim Python-generation path with better prompt structure, stronger output validation, and clearer failure handling, while preserving direct Python generation as the immediate runtime target.

**Architecture:** Build on the normalized scene and render-option split from stages 1 and 2. Move prompt construction into a dedicated builder, wrap model invocation behind a generation service, validate generated Python before accepting it, and keep metadata that makes behavior comparisons and debugging easier. Add an outlook section in docs, but do not yet migrate to structured LLM outputs compiled into Manim.

**Tech Stack:** FastAPI, OpenAI Agents SDK, Pydantic v2, pytest, Python AST/compile validation

---

### Task 1: Introduce a dedicated prompt builder

**Files:**
- Create: `layersense_agent/src/layersense_agent/services/prompt_builder.py`
- Modify: `layersense_agent/src/layersense_agent/agents/agent.py`
- Test: `layersense_agent/tests/unit/test_prompt_builder.py`

- [ ] **Step 1: Write the failing test**

```python
from layersense_agent.models.scene import NormalizedScene
from layersense_agent.services.prompt_builder import build_generation_prompt


def test_build_generation_prompt_contains_named_sections() -> None:
    scene = NormalizedScene.model_validate(
        {
            "elements": [],
            "appState": {"viewBackgroundColor": "#ffffff"},
            "files": {},
        }
    )

    prompt = build_generation_prompt(
        user_prompt="Animate the shape.",
        scene=scene,
    )

    assert "## User Intent" in prompt
    assert "## Scene Summary" in prompt
    assert "## Output Contract" in prompt
    assert "Animate the shape." in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_prompt_builder.py -q`
Expected: FAIL because `build_generation_prompt` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
from layersense_agent.models.scene import NormalizedScene


def build_generation_prompt(user_prompt: str, scene: NormalizedScene) -> str:
    return "\n\n".join(
        [
            "## User Intent\n" + user_prompt,
            "## Scene Summary\n" + scene.model_dump_json(indent=2),
            "## Output Contract\nOutput raw Python with a GeneratedScene class.",
        ]
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_prompt_builder.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_agent/src/layersense_agent/services/prompt_builder.py layersense_agent/src/layersense_agent/agents/agent.py layersense_agent/tests/unit/test_prompt_builder.py
git commit -m "feat(agent): build generation prompts from structured sections"
```

### Task 2: Add generated-code validation

**Files:**
- Create: `layersense_agent/src/layersense_agent/services/code_validation.py`
- Test: `layersense_agent/tests/unit/test_code_validation.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from layersense_agent.services.code_validation import validate_generated_scene_code


def test_validate_generated_scene_code_accepts_valid_scene() -> None:
    code = "from manim import Scene\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n"

    validate_generated_scene_code(code)


def test_validate_generated_scene_code_rejects_missing_generated_scene() -> None:
    code = "from manim import Scene\n\nclass OtherScene(Scene):\n    pass\n"

    with pytest.raises(ValueError, match="GeneratedScene"):
        validate_generated_scene_code(code)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_code_validation.py -q`
Expected: FAIL because validation service does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
import ast


def validate_generated_scene_code(code: str) -> None:
    compile(code, "<generated_scene>", "exec")
    tree = ast.parse(code)
    class_names = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    if "GeneratedScene" not in class_names:
        raise ValueError("GeneratedScene class missing from generated code")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_code_validation.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_agent/src/layersense_agent/services/code_validation.py layersense_agent/tests/unit/test_code_validation.py
git commit -m "feat(agent): validate generated manim code before write"
```

### Task 3: Move generation orchestration into a service

**Files:**
- Create: `layersense_agent/src/layersense_agent/services/generation.py`
- Modify: `layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py`
- Modify: `layersense_agent/tests/unit/test_animate_scene.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import AsyncMock, patch


def test_create_animation_calls_generation_service(client):
    c, _, _ = client

    with patch("layersense_agent.api.v1.endpoints.animate_scene.generate_scene_code", new=AsyncMock(return_value="from manim import Scene\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n")) as generate_mock:
        response = c.post(
            "/api/v1/animation",
            json={"prompt": "animate a circle", "scene": {"elements": [], "appState": {}, "files": {}}},
        )

    assert response.status_code == 200
    generate_mock.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_animate_scene.py -q`
Expected: FAIL because the endpoint still owns generation details directly.

- [ ] **Step 3: Write minimal implementation**

```python
async def generate_scene_code(user_prompt: str, scene: NormalizedScene, context: ManimAgentContext) -> str:
    prompt = build_generation_prompt(user_prompt=user_prompt, scene=scene)
    result = await Runner.run(manim_generator, prompt, context=context)
    code = strip_code_fences(result.final_output)
    validate_generated_scene_code(code)
    return code
```

Update the endpoint to call `generate_scene_code(...)` rather than building the prompt inline.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_animate_scene.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_agent/src/layersense_agent/services/generation.py layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py layersense_agent/tests/unit/test_animate_scene.py
git commit -m "refactor(agent): move generation flow into service layer"
```

### Task 4: Record generation metadata with the scene output

**Files:**
- Modify: `layersense_agent/src/layersense_agent/models/base.py`
- Modify: `layersense_agent/src/layersense_agent/services/generation.py`
- Modify: `layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py`
- Test: `layersense_agent/tests/unit/test_generation_metadata.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


def test_create_animation_writes_metadata_sidecar(client):
    c, _, _ = client
    response = c.post(
        "/api/v1/animation",
        json={"prompt": "animate a circle", "scene": {"elements": [], "appState": {}, "files": {}}},
    )

    assert response.status_code == 200
    scene_path = Path(response.json()["scene_path"])
    metadata_path = scene_path.with_suffix(".json")
    assert metadata_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_generation_metadata.py -q`
Expected: FAIL because no sidecar metadata is written.

- [ ] **Step 3: Write minimal implementation**

```python
class GenerationMetadata(BaseModel):
    model: str
    prompt_version: str
    normalized_scene_hash: str
    render_options_hash: str


metadata_path = scene_path.with_suffix(".json")
metadata_path.write_text(metadata.model_dump_json(indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_generation_metadata.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_agent/src/layersense_agent/models/base.py layersense_agent/src/layersense_agent/services/generation.py layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py layersense_agent/tests/unit/test_generation_metadata.py
git commit -m "feat(agent): persist generation metadata alongside scene output"
```

### Task 5: Improve generation failure handling at the endpoint boundary

**Files:**
- Modify: `layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py`
- Test: `layersense_agent/tests/unit/test_animate_scene.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import AsyncMock, patch


def test_create_animation_returns_error_when_generated_code_is_invalid(client):
    c, _, _ = client

    with patch(
        "layersense_agent.api.v1.endpoints.animate_scene.generate_scene_code",
        new=AsyncMock(side_effect=ValueError("GeneratedScene class missing from generated code")),
    ):
        response = c.post(
            "/api/v1/animation",
            json={"prompt": "animate a circle", "scene": {"elements": [], "appState": {}, "files": {}}},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "GeneratedScene class missing from generated code"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_animate_scene.py -q`
Expected: FAIL because the endpoint currently has no explicit validation-failure handling.

- [ ] **Step 3: Write minimal implementation**

```python
from fastapi import HTTPException

try:
    scene_code = await generate_scene_code(...)
except ValueError as exc:
    raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_animate_scene.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py layersense_agent/tests/unit/test_animate_scene.py
git commit -m "feat(agent): fail fast on invalid generated scene output"
```

### Task 6: Verify the stage, update docs, and preserve the future outlook

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/superpowers/specs/2026-04-24-prompt-to-manim-improvements-design.md`

- [ ] **Step 1: Update docs to describe the improved Python-generation path and future outlook**

```md
- The current agent path still targets direct Python generation, but now uses structured prompt building, generated-code validation, and metadata recording.
- A future direction remains open: structured animation outputs compiled into Manim code by deterministic application logic.
```

- [ ] **Step 2: Run focused tests**

Run: `uv run --all-packages pytest layersense_agent/tests/unit/test_prompt_builder.py layersense_agent/tests/unit/test_code_validation.py layersense_agent/tests/unit/test_generation_metadata.py layersense_agent/tests/unit/test_animate_scene.py -q`
Expected: PASS

- [ ] **Step 3: Run repo verification**

Run: `just lint`
Expected: PASS

Run: `just test`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add README.md docs/ROADMAP.md docs/superpowers/specs/2026-04-24-prompt-to-manim-improvements-design.md
git commit -m "docs: describe improved prompt-to-manim generation flow"
```
