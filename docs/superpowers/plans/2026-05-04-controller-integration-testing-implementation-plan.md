# Controller Integration Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class `layersense_controller` integration suite covering the FastAPI router boundary, Redis-like job-store semantics, and Taskiq in-process dispatch without requiring real Redis or a live worker.

**Architecture:** Keep the current `unit` suite unchanged and add three new integration modules with crisp boundaries: `TestClient(app)` for route behavior, async `fakeredis` for `RenderJobStore`, and `InMemoryBroker` for `run_render_job.kiq(...)`. Update repo docs after the new modules land so the controller no longer appears as the missing backend integration gap.

**Tech Stack:** pytest, FastAPI `TestClient`, `fakeredis`, Taskiq `InMemoryBroker`, `AsyncMock`, `monkeypatch`, `tmp_path`

---

## File Structure

- Modify: `pyproject.toml`
  - Add `fakeredis` to the root `dev` dependency group.
- Create: `layersense_controller/tests/integration/test_router_api.py`
  - Own controller `TestClient` integration coverage.
- Create: `layersense_controller/tests/integration/test_render_jobs_fakeredis.py`
  - Own `RenderJobStore` integration coverage using async `fakeredis`.
- Create: `layersense_controller/tests/integration/test_render_tasks_taskiq.py`
  - Own Taskiq in-process integration coverage using `InMemoryBroker`.
- Modify: `README.md`
  - Describe the new controller integration split and remove stale controller-gap language.

## Task 1: Add `fakeredis` To Dev Dependencies

**Files:**
- Modify: `pyproject.toml`
- Test: `uv sync --all-packages`

- [ ] **Step 1: Add the failing dependency reference**

Update the root `pyproject.toml` `dev` dependency group to include:

```toml
[dependency-groups]
dev = [
    "pdbpp==0.12.1",
    "rich==14.1.0",
    "ruff==0.13.0",
    "black==25.1.0",
    "isort==8.0.1",
    "mypy==1.18.1",
    "coverage==7.11.0",
    "pre-commit==4.5.1",
    "pytest==8.4.2",
    "pytest-asyncio==1.3.0",
    "pytest-mock==3.15.1",
    "pytest-recording==0.13.4",
    "requests==2.32.5",
    "fakeredis==2.31.0",
]
```

- [ ] **Step 2: Run dependency sync to verify the environment updates cleanly**

Run: `uv sync --all-packages`
Expected: the environment sync completes successfully with `fakeredis` available to pytest.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "test: add fakeredis for controller integration coverage"
```

## Task 2: Add FastAPI Router Integration Coverage

**Files:**
- Create: `layersense_controller/tests/integration/test_router_api.py`
- Test: `uv run --all-packages pytest layersense_controller/tests/integration/test_router_api.py -v`

- [ ] **Step 1: Write the failing integration module**

Create `layersense_controller/tests/integration/test_router_api.py` with:

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from layersense_controller.cache import hash_render_request
from layersense_controller.config import settings
from layersense_controller.main import app
from layersense_controller.render_jobs import RenderJobSnapshot

pytestmark = [pytest.mark.integration, pytest.mark.ai]


def _client() -> TestClient:
    return TestClient(app)


def test_health_returns_ok_from_app_boundary() -> None:
    """Return a healthy controller response from the app boundary."""
    with _client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_render_rejects_scene_outside_configured_scenes_dir(tmp_path, monkeypatch) -> None:
    """Reject render requests for scene files outside the configured scenes root."""
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    off_root_scene = tmp_path / "outside.py"
    off_root_scene.write_text("print('outside')\n")

    with _client() as client:
        response = client.post(
            "/render",
            json={"scene_path": str(off_root_scene), "conversation_id": "conversation-1"},
        )

    assert response.status_code == 400
    assert "configured scenes_dir" in response.json()["detail"]


def test_render_returns_cached_completed_job_snapshot(tmp_path, monkeypatch) -> None:
    """Return a completed snapshot immediately when cached preview and final artifacts exist."""
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    scene_path = scenes_dir / "demo_scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = hash_render_request(scene_path, {"background_color": None})

    preview = artifacts_dir / "scenes" / "_root" / "preview" / "demo_scene_preview.mp4"
    final = artifacts_dir / "scenes" / "_root" / "final" / "demo_scene_final.mp4"
    preview.parent.mkdir(parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"preview")
    final.write_bytes(b"final")

    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    content_hash: {
                        "scene_path": "demo_scene.py",
                        "scene_uuid": "demo_scene",
                        "preview": "_root/preview/demo_scene_preview.mp4",
                        "final": "_root/final/demo_scene_final.mp4",
                        "updated_at": "2026-05-04T00:00:00Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"demo_scene": content_hash},
            }
        )
    )

    async def fake_create_completed_job(
        self, *, job_id: str, conversation_id: str, preview_url: str, final_url: str
    ) -> RenderJobSnapshot:
        return RenderJobSnapshot(
            job_id=job_id,
            conversation_id=conversation_id,
            status="succeeded",
            version=1,
            preview_url=preview_url,
            final_url=final_url,
            error=None,
            stderr=None,
        )

    monkeypatch.setattr("layersense_controller.router.create_job_id", lambda: "job-123")
    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"create_completed_job": fake_create_completed_job})(),
    )

    with _client() as client:
        response = client.post(
            "/render", json={"scene_path": str(scene_path), "conversation_id": "conv-1"}
        )

    assert response.status_code == 200
    assert response.json()["job"]["status"] == "succeeded"
    assert response.json()["job"]["preview_url"] == f"/artifacts/by-hash/{content_hash}/preview"
    assert response.json()["job"]["final_url"] == f"/artifacts/by-hash/{content_hash}/final"


def test_render_enqueues_expected_taskiq_payload(tmp_path, monkeypatch) -> None:
    """Emit the expected Taskiq payload from the render API boundary."""
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    scene_path = scenes_dir / "generated_123.py"
    scene_path.write_text("print('demo')\n")

    async def fake_create_queued_job(self, *, job_id: str, conversation_id: str) -> RenderJobSnapshot:
        return RenderJobSnapshot(
            job_id=job_id,
            conversation_id=conversation_id,
            status="queued",
            version=1,
            preview_url=None,
            final_url=None,
            error=None,
            stderr=None,
        )

    monkeypatch.setattr("layersense_controller.router.create_job_id", lambda: "job-1")
    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"create_queued_job": fake_create_queued_job})(),
    )

    kiq_mock = AsyncMock(return_value=None)
    monkeypatch.setattr("layersense_controller.render_tasks.run_render_job.kiq", kiq_mock)

    with _client() as client:
        response = client.post(
            "/render",
            json={
                "scene_path": str(scene_path),
                "conversation_id": "conversation-1",
                "render_options": {"background_color": "#112233"},
            },
        )

    expected_hash = hash_render_request(scene_path, {"background_color": "#112233"})
    assert response.status_code == 200
    kiq_mock.assert_awaited_once_with(
        job_id="job-1",
        scene_path=str(scene_path),
        content_hash=expected_hash,
        conversation_id="conversation-1",
        render_options={"background_color": "#112233"},
    )


def test_get_render_job_returns_404_when_store_has_no_job(monkeypatch) -> None:
    """Return 404 when the requested render job does not exist."""
    calls = []

    async def fake_wait_for_newer_version(job_id: str, after_version, wait_seconds: int):
        calls.append((job_id, after_version, wait_seconds))
        return None

    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"wait_for_newer_version": fake_wait_for_newer_version})(),
    )

    with _client() as client:
        response = client.get("/render-jobs/missing-job")

    assert response.status_code == 404
    assert calls == [("missing-job", None, settings.render_job_wait_seconds)]


def test_get_render_job_clamps_wait_seconds_before_hitting_store(monkeypatch) -> None:
    """Clamp long-poll wait time to the configured controller maximum."""
    calls = []

    snapshot = RenderJobSnapshot(
        job_id="job-1",
        conversation_id="conversation-1",
        status="queued",
        version=1,
        preview_url=None,
        final_url=None,
        error=None,
        stderr=None,
    )

    async def fake_wait_for_newer_version(job_id: str, after_version, wait_seconds: int):
        calls.append((job_id, after_version, wait_seconds))
        return snapshot

    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"wait_for_newer_version": fake_wait_for_newer_version})(),
    )

    with _client() as client:
        response = client.get("/render-jobs/job-1?after_version=1&wait_seconds=999")

    assert response.status_code == 200
    assert calls == [("job-1", 1, settings.render_job_max_wait_seconds)]


def test_artifact_routes_return_404_for_missing_or_escaped_paths(tmp_path, monkeypatch) -> None:
    """Reject missing and escaped artifact paths at the app boundary."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    with _client() as client:
        missing = client.get("/artifacts/scenes/demo-scene")
        escaped = client.get("/artifacts/../outside.mp4")

    assert missing.status_code == 404
    assert escaped.status_code == 404
```

- [ ] **Step 2: Run the new module to observe the first failures**

Run: `uv run --all-packages pytest layersense_controller/tests/integration/test_router_api.py -v`
Expected: FAIL until the test module imports and monkeypatch targets are adjusted correctly.

- [ ] **Step 3: Fix the module until it passes without widening scope**

Make only the minimum test-side adjustments needed:

- keep `TestClient(app)` real
- keep `router.enqueue_render_job` real
- patch `layersense_controller.render_tasks.run_render_job.kiq` instead of bypassing the queue helper
- use `tmp_path` trees for real filesystem behavior

If a helper becomes necessary during implementation, keep it inside this test module:

```python
def _client() -> TestClient:
    return TestClient(app)
```

- [ ] **Step 4: Run the module to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/integration/test_router_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_controller/tests/integration/test_router_api.py
git commit -m "test: add controller router integration coverage"
```

## Task 3: Add `fakeredis` Render Job Store Integration Coverage

**Files:**
- Create: `layersense_controller/tests/integration/test_render_jobs_fakeredis.py`
- Test: `uv run --all-packages pytest layersense_controller/tests/integration/test_render_jobs_fakeredis.py -v`

- [ ] **Step 1: Write the failing integration module**

Create `layersense_controller/tests/integration/test_render_jobs_fakeredis.py` with:

```python
import asyncio

import fakeredis
import pytest

from layersense_controller.render_jobs import RenderJobStore

pytestmark = [pytest.mark.integration, pytest.mark.ai]


@pytest.mark.asyncio
async def test_create_queued_job_persists_snapshot_and_version() -> None:
    """Persist queued render jobs with their initial snapshot version."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RenderJobStore(redis, ttl_seconds=3600)

    job = await store.create_queued_job(job_id="job-1", conversation_id="conv-1")

    assert job.status == "queued"
    assert job.version == 1
    assert (await store.get_job("job-1")) == job


@pytest.mark.asyncio
async def test_create_completed_job_persists_succeeded_snapshot() -> None:
    """Persist succeeded render jobs with preview and final URLs."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RenderJobStore(redis, ttl_seconds=3600)

    job = await store.create_completed_job(
        job_id="job-1",
        conversation_id="conv-1",
        preview_url="/artifacts/by-hash/hash/preview",
        final_url="/artifacts/by-hash/hash/final",
    )

    assert job.status == "succeeded"
    assert job.preview_url == "/artifacts/by-hash/hash/preview"
    assert job.final_url == "/artifacts/by-hash/hash/final"


@pytest.mark.asyncio
async def test_update_job_bumps_version_and_publishes_event() -> None:
    """Publish an event when a render job snapshot version changes."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RenderJobStore(redis, ttl_seconds=3600)
    await store.create_queued_job(job_id="job-1", conversation_id="conv-1")

    subscriber = redis.pubsub()
    await subscriber.subscribe("layersense:render-jobs:job-1:events")

    updated = await store.update_job(job_id="job-1", status="preview_rendering")
    message = await subscriber.get_message(ignore_subscribe_messages=True, timeout=1.0)

    assert updated.version == 2
    assert updated.status == "preview_rendering"
    assert message is not None
    assert message["data"] == "2"


@pytest.mark.asyncio
async def test_wait_for_newer_version_returns_current_snapshot_immediately() -> None:
    """Return the current snapshot immediately when it is already newer than requested."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RenderJobStore(redis, ttl_seconds=3600)
    await store.create_queued_job(job_id="job-1", conversation_id="conv-1")
    await store.update_job(job_id="job-1", status="preview_rendering")

    job = await store.wait_for_newer_version(job_id="job-1", after_version=1, wait_seconds=1)

    assert job is not None
    assert job.version == 2
    assert job.status == "preview_rendering"


@pytest.mark.asyncio
async def test_wait_for_newer_version_returns_none_for_missing_job() -> None:
    """Return no snapshot when the requested render job does not exist."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RenderJobStore(redis, ttl_seconds=3600)

    job = await store.wait_for_newer_version(job_id="missing-job", after_version=1, wait_seconds=1)

    assert job is None


@pytest.mark.asyncio
async def test_wait_for_newer_version_unblocks_after_publish() -> None:
    """Wake a waiting long-poll read after a newer snapshot is published."""
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RenderJobStore(redis, ttl_seconds=3600)
    await store.create_queued_job(job_id="job-1", conversation_id="conv-1")

    waiter = asyncio.create_task(
        store.wait_for_newer_version(job_id="job-1", after_version=1, wait_seconds=2)
    )
    await asyncio.sleep(0)
    await store.update_job(job_id="job-1", status="preview_rendering")

    job = await asyncio.wait_for(waiter, timeout=2)

    assert job is not None
    assert job.version == 2
    assert job.status == "preview_rendering"
```

- [ ] **Step 2: Run the new module to observe the first failures**

Run: `uv run --all-packages pytest layersense_controller/tests/integration/test_render_jobs_fakeredis.py -v`
Expected: FAIL until `fakeredis` import/runtime behavior and pubsub timing are tuned correctly.

- [ ] **Step 3: Fix the module with the minimum stable changes**

Allowed adjustments during implementation:

- add a tiny local fixture for `FakeRedis(decode_responses=True)`
- increase the `asyncio.wait_for` timeout slightly if the publish path needs it
- add an `await asyncio.sleep(0)` yield before the update if the waiter must subscribe first

Keep all helpers local to this module. Do not change production `RenderJobStore` code for emulator quirks alone.

- [ ] **Step 4: Run the module to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/integration/test_render_jobs_fakeredis.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_controller/tests/integration/test_render_jobs_fakeredis.py
git commit -m "test: add fakeredis coverage for render job store"
```

## Task 4: Add Taskiq `InMemoryBroker` Integration Coverage

**Files:**
- Create: `layersense_controller/tests/integration/test_render_tasks_taskiq.py`
- Test: `uv run --all-packages pytest layersense_controller/tests/integration/test_render_tasks_taskiq.py -v`

- [ ] **Step 1: Write the failing integration module**

Create `layersense_controller/tests/integration/test_render_tasks_taskiq.py` with:

```python
import importlib

import pytest
from taskiq import InMemoryBroker

from layersense_controller.config import settings

pytestmark = [pytest.mark.integration, pytest.mark.ai]


@pytest.mark.asyncio
async def test_run_render_job_kiq_executes_pipeline_and_deserializes_render_options(
    monkeypatch, tmp_path
) -> None:
    """Execute the render task through Taskiq and deserialize render options."""
    broker = InMemoryBroker(await_inplace=True)

    import layersense_controller.broker as broker_module

    monkeypatch.setattr(broker_module, "broker", broker)
    render_tasks = importlib.reload(importlib.import_module("layersense_controller.render_tasks"))

    scene_path = tmp_path / "layersense_scenes" / "generated_123.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('demo')\n")
    monkeypatch.setattr(settings, "scenes_dir", tmp_path / "layersense_scenes")
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path / "artifacts")

    preview_path = tmp_path / "artifacts" / "scenes" / "_root" / "preview" / "scene_preview.mp4"
    final_path = tmp_path / "artifacts" / "scenes" / "_root" / "final" / "scene_final.mp4"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    transitions = []
    seen_render_options = []

    async def fake_render_preview(_scene_path, _content_hash, render_options=None):
        seen_render_options.append(render_options)
        preview_path.write_bytes(b"preview")
        return preview_path

    async def fake_render_final(_scene_path, _content_hash, render_options=None):
        seen_render_options.append(render_options)
        final_path.write_bytes(b"final")
        return final_path

    async def fake_update_job(self, job_id: str, status: str, **changes):
        transitions.append((status, changes))
        return None

    monkeypatch.setattr(render_tasks, "render_preview", fake_render_preview)
    monkeypatch.setattr(render_tasks, "render_final", fake_render_final)
    monkeypatch.setattr(
        render_tasks,
        "get_job_store",
        lambda: type("Store", (), {"update_job": fake_update_job})(),
    )
    monkeypatch.setattr(render_tasks, "store_cached_artifacts", lambda **_kwargs: None)

    await broker.startup()
    try:
        task = await render_tasks.run_render_job.kiq(
            job_id="job-1",
            scene_path=str(scene_path),
            content_hash="hash-1",
            conversation_id="conv-1",
            render_options={"background_color": "#112233"},
        )
        await task.wait_result(timeout=2)
    finally:
        await broker.shutdown()

    assert seen_render_options[0].background_color == "#112233"
    assert transitions == [
        ("preview_rendering", {}),
        ("waiting_for_final", {"preview_url": "/artifacts/by-hash/hash-1/preview"}),
        ("final_rendering", {}),
        (
            "succeeded",
            {
                "preview_url": "/artifacts/by-hash/hash-1/preview",
                "final_url": "/artifacts/by-hash/hash-1/final",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_run_render_job_kiq_marks_failed_when_rendering_raises(
    monkeypatch, tmp_path
) -> None:
    """Mark the render job failed when the Taskiq-executed pipeline raises a render error."""
    broker = InMemoryBroker(await_inplace=True)

    import layersense_controller.broker as broker_module
    from layersense_controller.render import RenderError

    monkeypatch.setattr(broker_module, "broker", broker)
    render_tasks = importlib.reload(importlib.import_module("layersense_controller.render_tasks"))

    scene_path = tmp_path / "layersense_scenes" / "generated_123.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('demo')\n")
    monkeypatch.setattr(settings, "scenes_dir", tmp_path / "layersense_scenes")
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path / "artifacts")

    transitions = []

    async def fake_render_preview(_scene_path, _content_hash, render_options=None):
        raise RenderError("manim exited with code 1", "stderr text")

    async def fake_update_job(self, job_id: str, status: str, **changes):
        transitions.append((status, changes))
        return None

    monkeypatch.setattr(render_tasks, "render_preview", fake_render_preview)
    monkeypatch.setattr(
        render_tasks,
        "get_job_store",
        lambda: type("Store", (), {"update_job": fake_update_job})(),
    )

    await broker.startup()
    try:
        task = await render_tasks.run_render_job.kiq(
            job_id="job-1",
            scene_path=str(scene_path),
            content_hash="hash-1",
            conversation_id="conv-1",
            render_options={"background_color": "#112233"},
        )
        await task.wait_result(timeout=2)
    finally:
        await broker.shutdown()

    assert transitions[-1] == (
        "failed",
        {"error": "manim exited with code 1", "stderr": "stderr text"},
    )
```

- [ ] **Step 2: Run the new module to observe the first failures**

Run: `uv run --all-packages pytest layersense_controller/tests/integration/test_render_tasks_taskiq.py -v`
Expected: FAIL until broker reload and in-memory execution details are wired correctly.

- [ ] **Step 3: Fix the module without broadening production code**

Allowed adjustments during implementation:

- switch the broker to `InMemoryBroker(await_inplace=True)` if direct in-place execution is the more stable fit
- reload `layersense_controller.render_tasks` after monkeypatching the broker module so the `@broker.task` decorator binds to the in-memory broker
- keep seam patching on the reloaded module, not on unrelated imports

Do not rely on mutating undocumented broker internals such as `is_worker_process` just to make the test pass.

Use the smallest stable helper if needed:

```python
def _reload_render_tasks_with_broker(monkeypatch, broker: InMemoryBroker):
    import layersense_controller.broker as broker_module

    monkeypatch.setattr(broker_module, "broker", broker)
    return importlib.reload(importlib.import_module("layersense_controller.render_tasks"))
```

- [ ] **Step 4: Run the module to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/integration/test_render_tasks_taskiq.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_controller/tests/integration/test_render_tasks_taskiq.py
git commit -m "test: add taskiq in-memory integration coverage"
```

## Task 5: Update Docs And Verify The Repo Entry Points

**Files:**
- Modify: `README.md`
- Test: `uv run --all-packages pytest tests/test_python_test_taxonomy.py -v`
- Test: `just test_python_integration`
- Test: `just lint`
- Test: `just test`

- [ ] **Step 1: Update the README testing taxonomy and controller status**

Revise `README.md` so it no longer says the controller lacks a real integration suite.

Update the testing taxonomy section to describe:

- `layersense_agent` still using `TestClient` plus VCR-backed model-boundary tests
- `layersense_controller` now using:
  - `test_router_api.py` for `TestClient` API-boundary coverage
  - `test_render_jobs_fakeredis.py` for `fakeredis` job-store coverage
  - `test_render_tasks_taskiq.py` for Taskiq `InMemoryBroker` coverage

Replace the stale controller gap lines with wording like:

```markdown
- `layersense_controller` now has a first integration slice under `layersense_controller/tests/integration/`.
- The controller integration suite is intentionally split by runtime boundary type:
  - `test_router_api.py`: `TestClient(app)` coverage for HTTP-facing controller behavior
  - `test_render_jobs_fakeredis.py`: Redis-like job store coverage using `fakeredis`
  - `test_render_tasks_taskiq.py`: Taskiq dispatch coverage using `InMemoryBroker`
```

- [ ] **Step 2: Run the taxonomy test**

Run: `uv run --all-packages pytest tests/test_python_test_taxonomy.py -v`
Expected: PASS because `layersense_controller/tests/integration/test_*.py` now exists.

- [ ] **Step 3: Run the shared integration suite**

Run: `just test_python_integration`
Expected: PASS with both agent and controller integration modules selected.

- [ ] **Step 4: Run repo lint**

Run: `just lint`
Expected: PASS

- [ ] **Step 5: Run full repo test entrypoint**

Run: `just test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: document controller integration testing split"
```

## Self-Review Checklist

- Spec coverage: this plan covers the approved dependency change, all three controller integration layers, doc updates, and repo verification.
- Placeholder scan: no `TODO`, `TBD`, or deferred implementation details appear inside the task steps.
- Type consistency: file names, module names, and helper targets match the current repo paths:
  - `layersense_controller/tests/integration/test_router_api.py`
  - `layersense_controller/tests/integration/test_render_jobs_fakeredis.py`
  - `layersense_controller/tests/integration/test_render_tasks_taskiq.py`

## Risks To Watch

- `fakeredis` pub/sub semantics may differ slightly from real Redis; for this pass that is acceptable because real Redis is explicitly deferred.
- If `run_render_job` ever gains FastAPI dependency injection, the `InMemoryBroker` layer will need `taskiq_fastapi.populate_dependency_context(...)` or a different boundary.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-04-controller-integration-testing-implementation-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
