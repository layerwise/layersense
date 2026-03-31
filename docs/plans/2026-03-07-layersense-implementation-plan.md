# LayerSense E2E Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a full E2E loop — draw in Excalidraw → AI generates Manim code → user edits in IDE → file-watcher triggers render → browser shows preview + HD video.

**Architecture:** The `layersense_agent` (FastAPI) translates Excalidraw JSON + prompt into a Manim `.py` file written to a shared `layersense_scenes/` volume. A file-watcher inside `layersense_controller` detects writes, hashes the file, and triggers a two-pass Manim render (low-quality preview first, then HD). The browser receives render events over WebSocket and displays the video. The Excalidraw canvas and video player live in `layersense_frontend/` (React + Vite).

**Tech Stack:** Python 3.14, FastAPI, OpenAI Agents SDK (`openai-agents`), watchdog, React 18, TypeScript, Vite, `@excalidraw/excalidraw`, Docker Compose, `manimcommunity/manim:latest`

**Design reference:** `docs/plans/2026-03-07-layersense-architecture-design.md`

---

## Conventions

- **Scene class name:** The AI agent always names the scene class `GeneratedScene`. Enforced in the system prompt.
- **Scenes directory:** Configurable via `SCENES_DIR` env var. Default: `./layersense_scenes` (host), `/scenes` (Docker).
- **Artifacts directory:** Configurable via `ARTIFACTS_DIR` env var. Default: `./layersense_artifacts` (host), `/artifacts` (Docker).
- **Scene filename:** `generated_<conversation_id>.py`
- **Artifact filename:** `<sha256>_preview.mp4`, `<sha256>_final.mp4`
- **Port map:** agent=8000, controller=8001, frontend=3000

---

## Task 1: Patch the agent — enforce `GeneratedScene` and write file to disk

**Why:** The `/api/v1/animation` endpoint currently discards the AI output and returns no scene path. We need it to (a) enforce `GeneratedScene` as the class name, (b) strip markdown fences from the output, (c) write the file, (d) return `scene_path`.

**Files:**
- Modify: `layersense_agent/src/layersense_agent/agents/agent.py`
- Modify: `layersense_agent/src/layersense_agent/models/base.py`
- Modify: `layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py`
- Test: `layersense_agent/tests/test_animate_scene.py`

---

### Step 1.1 — Add `AnimationCreatedResponse` to base models

In `layersense_agent/src/layersense_agent/models/base.py`, add after `ConversationCreatedResponse`:

```python
class AnimationCreatedResponse(BaseModel):
    conversation_id: str = Field(description="Unique identifier for this animation session.")
    scene_path: str = Field(description="Absolute path to the generated Manim scene file.")
```

---

### Step 1.2 — Update the agent system prompt to enforce `GeneratedScene`

In `layersense_agent/src/layersense_agent/agents/agent.py`, find `base_instructions` and replace the class name instruction section. At the end of the `base_instructions` string (before the closing `"""`), append:

```
## Critical Output Rules
1. The scene class MUST be named `GeneratedScene`. No other name is acceptable.
2. Output ONLY the raw Python code. Do NOT wrap it in markdown code fences (no ```python).
3. The code must be a complete, runnable Manim scene file starting with `from manim import *`.
```

---

### Step 1.3 — Add a helper to strip markdown fences

In `layersense_agent/src/layersense_agent/agents/agent.py`, add this function after the `manim_generator` definition:

```python
def strip_code_fences(code: str) -> str:
    """Remove markdown code fences if the model wraps output anyway."""
    code = code.strip()
    if code.startswith("```"):
        lines = code.splitlines()
        # drop first line (``` or ```python) and last line (```)
        code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return code.strip()
```

---

### Step 1.4 — Rewrite `animate_scene.py` endpoint

Replace the entire contents of `layersense_agent/src/layersense_agent/api/v1/endpoints/animate_scene.py`:

```python
import json
import os
from pathlib import Path
from uuid import uuid4

from agents import Runner
from fastapi import APIRouter, HTTPException

from layersense_agent.agents.agent import ManimAgentContext, manim_generator, strip_code_fences
from layersense_agent.models.base import AnimationCreatedResponse, AnimationInputs

router = APIRouter()

SCENES_DIR = Path(os.getenv("SCENES_DIR", "./layersense_scenes"))
EXAMPLE_JSON_PATH = Path("assets/example_json/example_circle_rectangle_freeform.json")


@router.post("/animation", response_model=AnimationCreatedResponse)
async def create_animation(inputs: AnimationInputs) -> AnimationCreatedResponse:
    """Translate an Excalidraw canvas + prompt into a Manim scene file."""
    conversation_id = str(uuid4())

    with open(EXAMPLE_JSON_PATH) as f:
        json_example = json.dumps(json.load(f))

    context = ManimAgentContext(json_example=json_example)
    user_prompt = inputs.prompt + "\n" + inputs.json_data

    result = await Runner.run(manim_generator, user_prompt, context=context)
    scene_code = strip_code_fences(result.final_output)

    SCENES_DIR.mkdir(parents=True, exist_ok=True)
    scene_path = SCENES_DIR / f"generated_{conversation_id}.py"
    scene_path.write_text(scene_code)

    return AnimationCreatedResponse(
        conversation_id=conversation_id,
        scene_path=str(scene_path),
    )
```

---

### Step 1.5 — Write the test

Create `layersense_agent/tests/test_animate_scene.py`:

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from layersense_agent.main import app

FAKE_CODE = "from manim import *\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENES_DIR", str(tmp_path))
    # Patch Runner.run so we don't call OpenAI
    mock_result = MagicMock()
    mock_result.final_output = FAKE_CODE
    with patch("layersense_agent.api.v1.endpoints.animate_scene.Runner") as mock_runner:
        mock_runner.run = AsyncMock(return_value=mock_result)
        with TestClient(app) as c:
            yield c, tmp_path


def test_create_animation_writes_file(client):
    c, tmp_path = client
    payload = {"prompt": "animate a circle", "json_data": "{}"}
    response = c.post("/api/v1/animation", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert "conversation_id" in body
    assert "scene_path" in body
    scene_path = Path(body["scene_path"])
    assert scene_path.exists()
    assert "GeneratedScene" in scene_path.read_text()


def test_strip_code_fences_removes_fences():
    from layersense_agent.agents.agent import strip_code_fences
    wrapped = "```python\nfrom manim import *\n```"
    assert strip_code_fences(wrapped) == "from manim import *"

def test_strip_code_fences_passthrough():
    from layersense_agent.agents.agent import strip_code_fences
    plain = "from manim import *"
    assert strip_code_fences(plain) == "from manim import *"
```

---

### Step 1.6 — Run the tests

```bash
cd layersense_agent
uv run pytest tests/test_animate_scene.py -v
```

Expected: 3 tests PASS.

---

### Step 1.7 — Commit

```bash
git add layersense_agent/
git commit -m "feat(agent): write generated scene to disk, enforce GeneratedScene class name"
```

---

## Task 2: Set up `layersense_controller` package structure

**Why:** The controller package has only a stub `pyproject.toml` with no source layout, no dependencies, and an empty Dockerfile. We need to create the src layout and install dependencies.

**Files:**
- Modify: `layersense_controller/pyproject.toml`
- Create: `layersense_controller/src/layersense_controller/__init__.py`
- Create: `layersense_controller/tests/__init__.py`

---

### Step 2.1 — Add dependencies to pyproject.toml

Replace the `dependencies` line in `layersense_controller/pyproject.toml`:

```toml
dependencies = [
    "fastapi[standard]>=0.116.1",
    "uvicorn>=0.35.0",
    "watchdog>=6.0.0",
    "httpx>=0.28.0",
    "pydantic>=2.12.5",
    "pydantic-settings>=2.9.1",
]
```

Also fix the hatch packages path (currently wrong):

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/layersense_controller"]
```

---

### Step 2.2 — Create the src layout

```bash
mkdir -p layersense_controller/src/layersense_controller
mkdir -p layersense_controller/tests
touch layersense_controller/src/layersense_controller/__init__.py
touch layersense_controller/tests/__init__.py
```

---

### Step 2.3 — Install the package

```bash
uv sync
```

Expected: resolves without errors.

---

### Step 2.4 — Commit

```bash
git add layersense_controller/
git commit -m "chore(controller): add package structure and dependencies"
```

---

## Task 3: Controller — config

**Why:** Centralise all path and port settings in one place so Dockerfiles and tests can override them via env vars.

**Files:**
- Create: `layersense_controller/src/layersense_controller/config.py`

---

### Step 3.1 — Write config.py

```python
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    scenes_dir: Path = Path("./layersense_scenes")
    artifacts_dir: Path = Path("./layersense_artifacts")
    host: str = "0.0.0.0"
    port: int = 8001

    model_config = {"env_prefix": "LAYERSENSE_"}


settings = Settings()
```

---

### Step 3.2 — Commit

```bash
git add layersense_controller/src/layersense_controller/config.py
git commit -m "feat(controller): add settings via pydantic-settings"
```

---

## Task 4: Controller — content hash + artifact cache

**Why:** Skip re-rendering if an identical file has already been rendered. Keyed by SHA-256 of file contents.

**Files:**
- Create: `layersense_controller/src/layersense_controller/cache.py`
- Test: `layersense_controller/tests/test_cache.py`

---

### Step 4.1 — Write cache.py

```python
import hashlib
from pathlib import Path

from layersense_controller.config import settings


def hash_file(path: Path) -> str:
    """Return SHA-256 hex digest of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preview_artifact(content_hash: str) -> Path:
    return settings.artifacts_dir / f"{content_hash}_preview.mp4"


def final_artifact(content_hash: str) -> Path:
    return settings.artifacts_dir / f"{content_hash}_final.mp4"


def is_cached(content_hash: str) -> tuple[bool, bool]:
    """Return (preview_exists, final_exists)."""
    return (
        preview_artifact(content_hash).exists(),
        final_artifact(content_hash).exists(),
    )
```

---

### Step 4.2 — Write test_cache.py

```python
import hashlib
from pathlib import Path

import pytest

from layersense_controller.cache import hash_file, is_cached, preview_artifact, final_artifact


@pytest.fixture()
def tmp_scene(tmp_path):
    f = tmp_path / "scene.py"
    f.write_text("from manim import *\n")
    return f


def test_hash_file_is_sha256(tmp_scene):
    expected = hashlib.sha256(tmp_scene.read_bytes()).hexdigest()
    assert hash_file(tmp_scene) == expected


def test_is_cached_false_when_no_files(tmp_path, monkeypatch):
    monkeypatch.setattr("layersense_controller.cache.settings.artifacts_dir", tmp_path)
    preview, final = is_cached("deadbeef")
    assert preview is False
    assert final is False


def test_is_cached_preview_true(tmp_path, monkeypatch):
    monkeypatch.setattr("layersense_controller.cache.settings.artifacts_dir", tmp_path)
    (tmp_path / "deadbeef_preview.mp4").touch()
    preview, final = is_cached("deadbeef")
    assert preview is True
    assert final is False
```

---

### Step 4.3 — Run the tests

```bash
uv run pytest layersense_controller/tests/test_cache.py -v
```

Expected: 3 tests PASS.

---

### Step 4.4 — Commit

```bash
git add layersense_controller/src/layersense_controller/cache.py layersense_controller/tests/test_cache.py
git commit -m "feat(controller): add content-hash cache for render artifacts"
```

---

## Task 5: Controller — Manim subprocess execution

**Why:** The controller needs to invoke `manim render` with the correct flags and capture stdout/stderr. Two passes: preview (`-ql`) and final (`-qh`).

**Files:**
- Create: `layersense_controller/src/layersense_controller/render.py`
- Test: `layersense_controller/tests/test_render.py`

---

### Step 5.1 — Write render.py

```python
import asyncio
import re
import shutil
from pathlib import Path

from layersense_controller.cache import final_artifact, preview_artifact
from layersense_controller.config import settings


class RenderError(Exception):
    def __init__(self, message: str, stderr: str) -> None:
        super().__init__(message)
        self.stderr = stderr


async def _run_manim(scene_path: Path, quality_flag: str) -> Path:
    """Run `manim render <quality_flag> <scene_path> GeneratedScene`.

    Returns the path manim writes the output to, then copies it to our
    artifacts directory under a content-hash name.
    """
    cmd = ["manim", "render", quality_flag, "--format=mp4", str(scene_path), "GeneratedScene"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RenderError(
            f"manim exited with code {proc.returncode}",
            stderr.decode(),
        )
    # Manim writes output to media/videos/<scene_stem>/<quality>/GeneratedScene.mp4
    # Parse the actual output path from stdout/stderr.
    output_path = _parse_output_path(stdout.decode() + stderr.decode(), scene_path)
    return output_path


def _parse_output_path(manim_output: str, scene_path: Path) -> Path:
    """Extract the rendered file path from manim's output."""
    # Manim prints "File ready at <path>" near the end.
    match = re.search(r"File ready at '?([^\s']+\.mp4)'?", manim_output)
    if match:
        return Path(match.group(1))
    # Fallback: glob for the most recently modified .mp4 under media/
    media_dir = Path("media")
    candidates = sorted(media_dir.rglob("GeneratedScene.mp4"), key=lambda p: p.stat().st_mtime)
    if candidates:
        return candidates[-1]
    raise RenderError("Could not locate rendered .mp4 output.", manim_output)


async def render_preview(scene_path: Path, content_hash: str) -> Path:
    """Render low-quality preview and store in artifacts dir."""
    output = await _run_manim(scene_path, "-ql")
    dest = preview_artifact(content_hash)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output, dest)
    return dest


async def render_final(scene_path: Path, content_hash: str) -> Path:
    """Render high-quality final video and store in artifacts dir."""
    output = await _run_manim(scene_path, "-qh")
    dest = final_artifact(content_hash)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output, dest)
    return dest
```

---

### Step 5.2 — Write test_render.py

Historical note: the render implementation below reflects the original March 7 plan and is no longer current. The live controller now uses explicit packaged Manim config resources, explicit nested `--output_file` paths, and deterministic artifact-rooted output discovery instead of parsing `GeneratedScene.mp4` paths from stdout.

```python
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from layersense_controller.render import RenderError, _parse_output_path, render_preview


def test_parse_output_path_from_file_ready_line(tmp_path):
    mp4 = tmp_path / "GeneratedScene.mp4"
    mp4.touch()
    output = f"Manim Community v0.18.0\nFile ready at '{mp4}'\n"
    result = _parse_output_path(output, Path("scene.py"))
    assert result == mp4


@pytest.mark.asyncio
async def test_render_preview_raises_on_nonzero_exit(tmp_path):
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"SyntaxError: invalid syntax"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(RenderError) as exc_info:
            await render_preview(tmp_path / "scene.py", "abc123")
    assert "SyntaxError" in exc_info.value.stderr
```

Note: `pytest-asyncio` must be installed. Add it to the dev deps in root `pyproject.toml`:
```toml
"pytest-asyncio>=0.26.0",
```

---

### Step 5.3 — Run the tests

```bash
uv run pytest layersense_controller/tests/test_render.py -v
```

Expected: 2 tests PASS.

---

### Step 5.4 — Commit

```bash
git add layersense_controller/src/layersense_controller/render.py layersense_controller/tests/test_render.py
git commit -m "feat(controller): add two-pass manim render execution"
```

---

## Task 6: Controller — WebSocket manager

**Why:** The browser needs real-time push notifications when preview and final renders are ready. A simple in-process manager handles broadcasting to all connected clients (single user, single connection is the expected case).

**Files:**
- Create: `layersense_controller/src/layersense_controller/websocket_manager.py`
- Test: `layersense_controller/tests/test_websocket_manager.py`

---

### Step 6.1 — Write websocket_manager.py

```python
import json
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    """Tracks active WebSocket connections and broadcasts JSON messages."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.remove(ws)

    async def broadcast(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event)
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)


manager = WebSocketManager()
```

---

### Step 6.2 — Write test_websocket_manager.py

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from layersense_controller.websocket_manager import WebSocketManager


@pytest.mark.asyncio
async def test_broadcast_sends_to_all_connections():
    mgr = WebSocketManager()
    ws1, ws2 = MagicMock(), MagicMock()
    ws1.send_text = AsyncMock()
    ws2.send_text = AsyncMock()
    mgr._connections = [ws1, ws2]

    await mgr.broadcast({"type": "preview_ready", "url": "/artifacts/foo.mp4"})

    ws1.send_text.assert_awaited_once()
    ws2.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_broadcast_removes_dead_connections():
    mgr = WebSocketManager()
    ws = MagicMock()
    ws.send_text = AsyncMock(side_effect=Exception("disconnected"))
    mgr._connections = [ws]

    await mgr.broadcast({"type": "render_ready"})

    assert len(mgr._connections) == 0
```

---

### Step 6.3 — Run the tests

```bash
uv run pytest layersense_controller/tests/test_websocket_manager.py -v
```

Expected: 2 tests PASS.

---

### Step 6.4 — Commit

```bash
git add layersense_controller/src/layersense_controller/websocket_manager.py \
        layersense_controller/tests/test_websocket_manager.py
git commit -m "feat(controller): add WebSocket broadcast manager"
```

---

## Task 7: Controller — router (`/render`, `/ws`, `/artifacts`, `/health`)

**Why:** Wire together the cache, render, and WebSocket modules behind HTTP endpoints.

**Files:**
- Create: `layersense_controller/src/layersense_controller/router.py`
- Test: `layersense_controller/tests/test_router.py`

---

### Step 7.1 — Write router.py

```python
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from layersense_controller.cache import final_artifact, hash_file, is_cached, preview_artifact
from layersense_controller.config import settings
from layersense_controller.render import RenderError, render_final, render_preview
from layersense_controller.websocket_manager import manager

router = APIRouter()


class RenderRequest(BaseModel):
    scene_path: str
    conversation_id: str


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive; client sends pings
    except WebSocketDisconnect:
        manager.disconnect(ws)


@router.get("/artifacts/{filename}")
async def serve_artifact(filename: str) -> FileResponse:
    path = settings.artifacts_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path, media_type="video/mp4")


@router.post("/render")
async def trigger_render(req: RenderRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    scene_path = Path(req.scene_path)
    if not scene_path.exists():
        raise HTTPException(status_code=404, detail=f"Scene file not found: {scene_path}")

    content_hash = hash_file(scene_path)
    preview_exists, final_exists = is_cached(content_hash)

    if preview_exists and final_exists:
        await manager.broadcast({
            "type": "artifact_ready",
            "conversation_id": req.conversation_id,
            "preview_url": f"/artifacts/{content_hash}_preview.mp4",
            "final_url": f"/artifacts/{content_hash}_final.mp4",
        })
        return {"status": "cached"}

    background_tasks.add_task(
        _render_pipeline, scene_path, content_hash, req.conversation_id
    )
    return {"status": "queued"}


async def _render_pipeline(scene_path: Path, content_hash: str, conversation_id: str) -> None:
    """Two-pass render: low-quality preview first, then HD final."""
    try:
        if not preview_artifact(content_hash).exists():
            await render_preview(scene_path, content_hash)
            await manager.broadcast({
                "type": "preview_ready",
                "conversation_id": conversation_id,
                "url": f"/artifacts/{content_hash}_preview.mp4",
            })

        if not final_artifact(content_hash).exists():
            await render_final(scene_path, content_hash)
            await manager.broadcast({
                "type": "render_ready",
                "conversation_id": conversation_id,
                "url": f"/artifacts/{content_hash}_final.mp4",
            })

    except RenderError as exc:
        await manager.broadcast({
            "type": "render_failed",
            "conversation_id": conversation_id,
            "error": str(exc),
            "stderr": exc.stderr,
        })
```

---

### Step 7.2 — Write test_router.py

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from layersense_controller.main import app  # created in Task 8


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("layersense_controller.router.settings.artifacts_dir", tmp_path)
    with TestClient(app) as c:
        yield c, tmp_path


def test_health(client):
    c, _ = client
    assert c.get("/health").json() == {"status": "ok"}


def test_render_returns_404_for_missing_file(client):
    c, _ = client
    resp = c.post("/render", json={"scene_path": "/nonexistent/scene.py", "conversation_id": "abc"})
    assert resp.status_code == 404


def test_render_returns_cached_when_artifacts_exist(tmp_path, monkeypatch):
    scene = tmp_path / "scene.py"
    scene.write_text("from manim import *\n")
    import hashlib
    h = hashlib.sha256(scene.read_bytes()).hexdigest()
    (tmp_path / f"{h}_preview.mp4").touch()
    (tmp_path / f"{h}_final.mp4").touch()

    monkeypatch.setattr("layersense_controller.router.settings.artifacts_dir", tmp_path)

    broadcast_mock = AsyncMock()
    with patch("layersense_controller.router.manager.broadcast", broadcast_mock):
        from fastapi.testclient import TestClient
        from layersense_controller.main import app
        with TestClient(app) as c:
            resp = c.post("/render", json={"scene_path": str(scene), "conversation_id": "abc"})

    assert resp.json()["status"] == "cached"
    broadcast_mock.assert_awaited_once()
```

---

### Step 7.3 — Run the tests (will fail until Task 8 creates main.py)

Skip for now — run after Task 8.

---

### Step 7.4 — Commit

```bash
git add layersense_controller/src/layersense_controller/router.py \
        layersense_controller/tests/test_router.py
git commit -m "feat(controller): add /render, /ws, /artifacts, /health endpoints"
```

---

## Task 8: Controller — `main.py` + lifespan (file-watcher)

**Why:** The FastAPI app entry point. The file-watcher runs as a background thread started in the lifespan event, so it shares the process with the HTTP server.

**Files:**
- Create: `layersense_controller/src/layersense_controller/watcher.py`
- Create: `layersense_controller/src/layersense_controller/main.py`

---

### Step 8.1 — Write watcher.py

```python
import logging
import threading

import httpx
from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from layersense_controller.config import settings

logger = logging.getLogger(__name__)


class SceneFileHandler(FileSystemEventHandler):
    """Calls POST /render whenever a .py file is created or modified."""

    def _handle(self, path: str) -> None:
        if not path.endswith(".py"):
            return
        # Extract conversation_id from filename: generated_<uuid>.py
        stem = path.rsplit("/", 1)[-1].replace(".py", "")
        conversation_id = stem.removeprefix("generated_") if stem.startswith("generated_") else stem
        try:
            httpx.post(
                f"http://localhost:{settings.port}/render",
                json={"scene_path": path, "conversation_id": conversation_id},
                timeout=5,
            )
        except Exception as exc:
            logger.warning("Failed to notify controller of scene change: %s", exc)

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._handle(event.src_path)

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._handle(event.src_path)


def start_watcher() -> Observer:
    settings.scenes_dir.mkdir(parents=True, exist_ok=True)
    handler = SceneFileHandler()
    observer = Observer()
    observer.schedule(handler, str(settings.scenes_dir), recursive=False)
    observer.start()
    logger.info("File watcher started on %s", settings.scenes_dir)
    return observer
```

---

### Step 8.2 — Write main.py

```python
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from layersense_controller.router import router
from layersense_controller.watcher import start_watcher


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    observer = start_watcher()
    yield
    observer.stop()
    observer.join()


app = FastAPI(title="LayerSense Controller", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
```

---

### Step 8.3 — Run all controller tests

```bash
uv run pytest layersense_controller/tests/ -v
```

Expected: all tests PASS.

---

### Step 8.4 — Commit

```bash
git add layersense_controller/src/layersense_controller/watcher.py \
        layersense_controller/src/layersense_controller/main.py
git commit -m "feat(controller): add FastAPI app with lifespan file-watcher"
```

---

## Task 9: Controller — Dockerfile

**Why:** The controller container must include Manim (and its heavy dependencies: ffmpeg, LaTeX, Cairo). Build on top of `manimcommunity/manim:latest`, then add uv and our package.

**Files:**
- Modify: `layersense_controller/Dockerfile`

---

### Step 9.1 — Write the Dockerfile

```dockerfile
FROM manimcommunity/manim:latest

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy package files
COPY pyproject.toml .
COPY src/ src/

# Install our package (no dev deps in prod)
RUN uv pip install --system --no-cache .

ENV LAYERSENSE_SCENES_DIR=/scenes
ENV LAYERSENSE_ARTIFACTS_DIR=/artifacts

EXPOSE 8001

CMD ["uvicorn", "layersense_controller.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

---

### Step 9.2 — Commit

```bash
git add layersense_controller/Dockerfile
git commit -m "feat(controller): add Dockerfile based on manimcommunity/manim"
```

---

## Task 10: Agent — Dockerfile

**Why:** The agent needs Python + our dependencies. No Manim needed here.

**Files:**
- Modify: `layersense_agent/Dockerfile`

---

### Step 10.1 — Write the Dockerfile

```dockerfile
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
COPY assets/ assets/

RUN uv pip install --system --no-cache .

ENV SCENES_DIR=/scenes

EXPOSE 8000

CMD ["uvicorn", "layersense_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

### Step 10.2 — Commit

```bash
git add layersense_agent/Dockerfile
git commit -m "feat(agent): add Dockerfile"
```

---

## Task 11: Frontend — scaffold React + Vite + TypeScript

**Why:** Create the `layersense_frontend/` package with Excalidraw and the project dependencies.

**Files:**
- Create: `layersense_frontend/` (new directory tree)

---

### Step 11.1 — Scaffold with Vite

```bash
cd layersense_frontend  # already created, or: mkdir layersense_frontend && cd layersense_frontend
npm create vite@latest . -- --template react-ts
npm install
npm install @excalidraw/excalidraw
```

Expected: `node_modules/` populated, `src/App.tsx` exists.

---

### Step 11.2 — Verify the dev server starts

```bash
npm run dev
```

Expected: Vite dev server at `http://localhost:5173`. Ctrl+C to stop.

---

### Step 11.3 — Commit

```bash
git add layersense_frontend/
git commit -m "feat(frontend): scaffold React + Vite + TypeScript with Excalidraw"
```

---

## Task 12: Frontend — Excalidraw canvas + prompt + Generate button

**Why:** The user draws in Excalidraw, types a prompt, clicks Generate. The app POSTs to the agent and returns a `conversation_id` and `scene_path`.

**Files:**
- Modify: `layersense_frontend/src/App.tsx`
- Create: `layersense_frontend/src/components/Canvas.tsx`
- Create: `layersense_frontend/src/api.ts`

---

### Step 12.1 — Write api.ts

```typescript
// layersense_frontend/src/api.ts

const AGENT_BASE = "http://localhost:8000";

export interface AnimationCreatedResponse {
  conversation_id: string;
  scene_path: string;
}

export async function createAnimation(
  prompt: string,
  jsonData: string
): Promise<AnimationCreatedResponse> {
  const res = await fetch(`${AGENT_BASE}/api/v1/animation`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, json_data: jsonData }),
  });
  if (!res.ok) throw new Error(`Agent error: ${res.statusText}`);
  return res.json();
}
```

---

### Step 12.2 — Write Canvas.tsx

```tsx
// layersense_frontend/src/components/Canvas.tsx
import { Excalidraw } from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";
import { ExcalidrawElement } from "@excalidraw/excalidraw/types/element/types";
import { AppState, BinaryFiles } from "@excalidraw/excalidraw/types/types";
import { useRef } from "react";

interface Props {
  onExport: (json: string) => void;
}

export function Canvas({ onExport }: Props) {
  const elementsRef = useRef<readonly ExcalidrawElement[]>([]);
  const appStateRef = useRef<AppState | null>(null);

  function handleChange(
    elements: readonly ExcalidrawElement[],
    appState: AppState,
    _files: BinaryFiles
  ) {
    elementsRef.current = elements;
    appStateRef.current = appState;
  }

  function handleExport() {
    const payload = {
      type: "excalidraw",
      version: 2,
      source: "http://localhost:3000",
      elements: elementsRef.current,
      appState: appStateRef.current ?? {},
      files: {},
    };
    onExport(JSON.stringify(payload));
  }

  return (
    <div style={{ height: "60vh", border: "1px solid #ccc" }}>
      <Excalidraw onChange={handleChange} />
      <button onClick={handleExport} style={{ marginTop: 8 }}>
        Export Canvas
      </button>
    </div>
  );
}
```

---

### Step 12.3 — Write App.tsx

```tsx
// layersense_frontend/src/App.tsx
import { useState } from "react";
import { Canvas } from "./components/Canvas";
import { VideoPlayer } from "./components/VideoPlayer";
import { createAnimation } from "./api";

export default function App() {
  const [prompt, setPrompt] = useState("");
  const [canvasJson, setCanvasJson] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");

  async function handleGenerate() {
    if (!canvasJson) { setStatus("Export the canvas first."); return; }
    if (!prompt)     { setStatus("Enter a prompt."); return; }
    setStatus("Generating...");
    try {
      const result = await createAnimation(prompt, canvasJson);
      setConversationId(result.conversation_id);
      setStatus(`Scene written to ${result.scene_path}. Waiting for render...`);
    } catch (e) {
      setStatus(`Error: ${e}`);
    }
  }

  return (
    <div style={{ fontFamily: "sans-serif", padding: 16, maxWidth: 1200 }}>
      <h1>LayerSense</h1>

      <Canvas onExport={setCanvasJson} />

      <div style={{ marginTop: 16 }}>
        <textarea
          rows={3}
          style={{ width: "100%" }}
          placeholder="Describe the animation (e.g. 'Animate the circle with Create, then the rectangle with GrowFromCenter')"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
        <button onClick={handleGenerate} style={{ marginTop: 8 }}>
          Generate
        </button>
        <p style={{ color: "#555" }}>{status}</p>
      </div>

      {conversationId && (
        <VideoPlayer conversationId={conversationId} onStatus={setStatus} />
      )}
    </div>
  );
}
```

---

### Step 12.4 — Commit

```bash
git add layersense_frontend/src/
git commit -m "feat(frontend): add Excalidraw canvas, prompt, and generate button"
```

---

## Task 13: Frontend — WebSocket + VideoPlayer

**Why:** The browser needs to listen for `preview_ready` and `render_ready` events from the controller and update the video player accordingly.

**Files:**
- Create: `layersense_frontend/src/components/VideoPlayer.tsx`
- Create: `layersense_frontend/src/hooks/useRenderEvents.ts`

---

### Step 13.1 — Write useRenderEvents.ts

```typescript
// layersense_frontend/src/hooks/useRenderEvents.ts
import { useEffect, useState } from "react";

const CONTROLLER_WS = "ws://localhost:8001/ws";

export interface RenderState {
  previewUrl: string | null;
  finalUrl: string | null;
  error: string | null;
}

export function useRenderEvents(conversationId: string | null): RenderState {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [finalUrl, setFinalUrl]     = useState<string | null>(null);
  const [error, setError]           = useState<string | null>(null);

  useEffect(() => {
    if (!conversationId) return;
    const ws = new WebSocket(CONTROLLER_WS);

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.conversation_id !== conversationId) return;
      if (msg.type === "preview_ready")  setPreviewUrl(`http://localhost:8001${msg.url}`);
      if (msg.type === "render_ready")   setFinalUrl(`http://localhost:8001${msg.url}`);
      if (msg.type === "artifact_ready") {
        setPreviewUrl(`http://localhost:8001${msg.preview_url}`);
        setFinalUrl(`http://localhost:8001${msg.final_url}`);
      }
      if (msg.type === "render_failed")  setError(msg.error);
    };

    return () => ws.close();
  }, [conversationId]);

  return { previewUrl, finalUrl, error };
}
```

---

### Step 13.2 — Write VideoPlayer.tsx

```tsx
// layersense_frontend/src/components/VideoPlayer.tsx
import { useRenderEvents } from "../hooks/useRenderEvents";

interface Props {
  conversationId: string;
  onStatus: (s: string) => void;
}

export function VideoPlayer({ conversationId, onStatus }: Props) {
  const { previewUrl, finalUrl, error } = useRenderEvents(conversationId);

  if (error) {
    onStatus(`Render failed: ${error}`);
    return <p style={{ color: "red" }}>Render failed: {error}</p>;
  }

  const url = finalUrl ?? previewUrl;
  if (!url) return <p style={{ color: "#999" }}>Render in progress...</p>;

  if (finalUrl) onStatus("Render complete.");
  else          onStatus("Preview ready — HD render in progress...");

  return (
    <div style={{ marginTop: 16 }}>
      <h3>{finalUrl ? "Final Render" : "Preview"}</h3>
      <video key={url} src={url} controls autoPlay style={{ maxWidth: "100%" }} />
    </div>
  );
}
```

---

### Step 13.3 — Verify the frontend compiles

```bash
cd layersense_frontend
npm run build
```

Expected: build succeeds, no TypeScript errors.

---

### Step 13.4 — Commit

```bash
git add layersense_frontend/src/
git commit -m "feat(frontend): add WebSocket render events and video player"
```

---

## Task 14: Frontend — Dockerfile

**Files:**
- Create: `layersense_frontend/Dockerfile`
- Create: `layersense_frontend/nginx.conf`

---

### Step 14.1 — Write nginx.conf

```nginx
server {
    listen 3000;
    root /usr/share/nginx/html;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

---

### Step 14.2 — Write Dockerfile

```dockerfile
FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
```

---

### Step 14.3 — Commit

```bash
git add layersense_frontend/Dockerfile layersense_frontend/nginx.conf
git commit -m "feat(frontend): add Dockerfile with nginx"
```

---

## Task 15: Wire up `docker-compose.yml`

**Why:** Bring all services together with correct port bindings, environment variables, and shared volumes.

**Files:**
- Modify: `docker-compose.yml`

---

### Step 15.1 — Rewrite docker-compose.yml

```yaml
services:
  layersense_agent:
    build:
      context: ./layersense_agent
    ports:
      - "8000:8000"
    environment:
      - SCENES_DIR=/scenes
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    volumes:
      - scenes:/scenes
      - ./assets:/app/assets:ro

  layersense_controller:
    build:
      context: ./layersense_controller
    ports:
      - "8001:8001"
    environment:
      - LAYERSENSE_SCENES_DIR=/scenes
      - LAYERSENSE_ARTIFACTS_DIR=/artifacts
      - LAYERSENSE_PORT=8001
    volumes:
      - scenes:/scenes
      - artifacts:/artifacts

  layersense_frontend:
    build:
      context: ./layersense_frontend
    ports:
      - "3000:3000"
    depends_on:
      - layersense_agent
      - layersense_controller

volumes:
  scenes:
  artifacts:
```

---

### Step 15.2 — Verify compose config is valid

```bash
docker compose config
```

Expected: prints merged config without errors.

---

### Step 15.3 — Commit

```bash
git add docker-compose.yml
git commit -m "chore: wire all services in docker-compose with shared volumes"
```

---

## Task 16: Integration smoke test

**Why:** Verify the full loop works before calling the implementation complete.

---

### Step 16.1 — Start all services

```bash
docker compose up --build
```

Expected: all three services start, controller logs "File watcher started".

Reality note: this step is currently stale relative to the repo root `docker-compose.yml`, which is not yet wired to start the agent, controller, and frontend stack described in this plan. Use this section as the intended smoke-test shape, not the exact current startup procedure.

---

### Step 16.2 — Open the frontend

Navigate to `http://localhost:3000`.

Expected: Excalidraw canvas visible, prompt textarea visible, Generate button visible.

---

### Step 16.3 — Draw and generate

1. Draw a circle in the canvas.
2. Click "Export Canvas".
3. Type: `Animate the circle with Create`.
4. Click "Generate".

Expected: status changes to "Scene written to /scenes/generated_<id>.py. Waiting for render..."

---

### Step 16.4 — Verify file watcher fired

In the controller logs:

```
File watcher started on /scenes
INFO:     POST /render 200
```

---

### Step 16.5 — Wait for preview

Expected within ~30 seconds: video player appears with a low-quality preview.

---

### Step 16.6 — Wait for final render

Expected within ~2 minutes: video player updates to HD video, status = "Render complete."

---

### Step 16.7 — IDE edit loop

1. Open `./layersense_scenes/generated_<id>.py` in your local IDE.
2. Add `self.wait(2)` after the last animation.
3. Save the file.

Expected: controller re-renders, new preview appears in the browser.

---

## Open Questions (resolve before implementation)

These are flagged in the design doc and deferred for now:

1. **Scene class detection fallback:** If the agent produces a class other than `GeneratedScene` (e.g. due to a model regression), the render will fail silently. A future improvement: parse the AST to extract the actual class name before rendering.

2. **Multi-turn conversation:** The `conversation_id` is wired through but there is no conversation history. A second "Generate" creates a new `conversation_id` and a new file. Multi-turn (refine the same animation) is left for a future milestone.

3. **`OPENAI_API_KEY` management:** The docker-compose uses `${OPENAI_API_KEY}` from the host environment. Document this in README. A `.env` file is supported by docker-compose automatically (see `.env.template`).

4. **Startup ergonomics drift:** The original implementation plan assumed a coherent Docker-first startup flow. Current validation may require manual service startup until compose wiring is brought back in sync.
