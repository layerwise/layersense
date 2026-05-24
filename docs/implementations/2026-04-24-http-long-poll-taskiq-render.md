# HTTP Long-Poll Taskiq Render Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current websocket-driven render updates with a `job_id`-based HTTP long-poll flow backed by Redis and a Taskiq worker, while preserving preview-first playback and existing artifact routes.

**Architecture:** Keep `layersense_controller.router` as the HTTP edge for render requests and cache short-circuiting. Move render execution into one Taskiq task per render job, persist ephemeral job snapshots in Redis, and wake long-poll requests with Redis pub/sub notifications after each version bump.

**Tech Stack:** FastAPI, redis asyncio client, Taskiq, Taskiq Redis broker, Pydantic settings, pytest, Vitest, Docker Compose, React, Vite

---

## File Structure

### Controller Python package

- Modify: `layersense_controller/pyproject.toml`
  - Declare controller-local runtime dependencies for FastAPI, Uvicorn, Redis, Taskiq, and Taskiq Redis.
- Modify: `layersense_controller/src/layersense_controller/config.py`
  - Add Redis URL, render-job TTL, default long-poll wait, and max long-poll wait settings.
- Create: `layersense_controller/src/layersense_controller/broker.py`
  - Own Redis client creation, Taskiq broker wiring, and cached per-process accessors.
- Create: `layersense_controller/src/layersense_controller/render_jobs.py`
  - Own render job models, Redis key layout, snapshot serialization, version bumps, pub/sub notifications, and long-poll wait logic.
- Create: `layersense_controller/src/layersense_controller/render_runtime.py`
  - Own shared render helpers used by both router and worker code.
- Create: `layersense_controller/src/layersense_controller/render_tasks.py`
  - Own Taskiq render task that runs preview then final and updates Redis job state.
- Create: `layersense_controller/src/layersense_controller/worker.py`
  - Provide worker import path/entrypoint.
- Modify: `layersense_controller/src/layersense_controller/router.py`
  - Remove `/ws`, change `POST /render` contract, add `GET /render-jobs/{job_id}`, dispatch Taskiq work, and use job store instead of websocket broadcasts.
- Modify: `layersense_controller/src/layersense_controller/main.py`
  - Keep app health stable and ensure router-only HTTP startup still works.
- Delete: `layersense_controller/src/layersense_controller/websocket_manager.py`
  - Remove obsolete websocket runtime.

### Controller tests

- Create: `layersense_controller/tests/unit/test_render_jobs.py`
  - Unit tests for snapshot creation, pub/sub notification, and long-poll wait behavior.
- Create: `layersense_controller/tests/unit/test_render_tasks.py`
  - Unit tests for preview/final state progression and failure handling.
- Modify: `layersense_controller/tests/unit/test_router.py`
  - Assert job-based `POST /render` and `GET /render-jobs/{job_id}` behavior.
- Modify: `layersense_controller/tests/unit/test_cache.py`
  - Keep cache-index behavior and document the remaining file-lock limitation if no lock refactor is added in this pass.
- Modify: `layersense_controller/tests/unit/test_main.py`
  - Keep app startup/health assertions aligned after websocket removal.
- Delete: `layersense_controller/tests/unit/test_websocket_manager.py`
  - Remove obsolete websocket-only coverage.

Existing `test_router.py` coverage must be migrated deliberately rather than deleted opportunistically.

Move these existing `_render_pipeline`-centric tests into `test_render_tasks.py` with job-state assertions replacing websocket broadcasts:

- `test_render_pipeline_renders_non_generated_scene_when_hash_match_belongs_to_other_scene`
- `test_render_pipeline_keeps_latest_generated_scene_uuid_mapping`
- `test_render_pipeline_broadcasts_cached_final_after_rendering_missing_preview`
- `test_render_pipeline_broadcasts_cached_preview_before_rendering_missing_final`
- `test_render_pipeline_logs_and_broadcasts_render_error`
- `test_render_pipeline_broadcasts_failure_for_unexpected_errors`
- `test_render_queues_and_broadcasts_preview_and_final`
- `test_render_queued_path_uses_canonical_scene_outputs_for_cache_check`

Keep these route-focused behaviors in `test_router.py` and rewrite them for the new HTTP contract:

- missing scene file and directory validation
- configured `scenes_dir` validation
- cached complete response
- queued response for uncached or mismatched manual scenes
- artifact route serving and scene route fallback behavior
- generated-scene cached-hash reuse rules
- non-generated scene hash-collision rerender decision at `POST /render`

### Frontend app

- Modify: `layersense_frontend/src/types.ts`
  - Replace websocket event types with render-job snapshot types.
- Modify: `layersense_frontend/src/api.ts`
  - Keep `queueRender`, add `getRenderJob`, and update response types.
- Modify: `layersense_frontend/src/api.test.ts`
  - Assert new `POST /render` and `GET /render-jobs/{job_id}` contracts.
- Create: `layersense_frontend/src/hooks/useRenderJob.ts`
  - Long-poll the controller using `job_id`, `after_version`, and `wait_seconds`.
- Create: `layersense_frontend/src/hooks/useRenderJob.test.ts`
  - Unit tests for long-poll behavior.
- Modify: `layersense_frontend/src/App.tsx`
  - Track `jobId` and current job snapshot instead of websocket conversation filtering.
- Modify: `layersense_frontend/src/App.test.tsx`
  - Assert queue -> preview -> final -> failure behavior through polling snapshots.
- Delete: `layersense_frontend/src/hooks/useRenderEvents.ts`
  - Remove obsolete websocket hook.
- Delete: `layersense_frontend/src/hooks/useRenderEvents.test.ts`
  - Remove obsolete websocket tests.

### Compose, e2e, docs

- Modify: `docker-compose.yml`
  - Add `redis` and `controller-worker` services.
- Modify: `docker-compose.e2e.yml`
  - Carry new services into the assistant-friendly stack.
- Modify: `layersense_controller/Dockerfile`
  - Keep the image reusable for both API and worker commands.
- Modify: `scripts/run_e2e.sh`
  - Remove websocket env export and wait for Redis-backed stack.
- Modify: `tests/e2e/test_dev_stack_e2e.py`
  - Replace websocket helpers with job polling helpers.
- Modify: `README.md`
  - Describe HTTP long-poll + Redis/Taskiq flow.
- Modify: `docs/ROADMAP.md`
  - Update active runtime-path wording.
- Modify: `AGENTS.md`
  - Update repo runtime guidance.

## Task 1: Controller Dependencies And Runtime Config

**Files:**
- Modify: `layersense_controller/pyproject.toml`
- Modify: `layersense_controller/src/layersense_controller/config.py`
- Create: `layersense_controller/src/layersense_controller/broker.py`
- Test: `layersense_controller/tests/unit/test_main.py`

- [ ] **Step 1: Write the failing config/import test**

Add this test near the bottom of `layersense_controller/tests/unit/test_main.py`:

```python
def test_settings_expose_redis_and_long_poll_fields(monkeypatch) -> None:
    monkeypatch.setenv("LAYERSENSE_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("LAYERSENSE_RENDER_JOB_TTL_SECONDS", "7200")
    monkeypatch.setenv("LAYERSENSE_RENDER_JOB_WAIT_SECONDS", "20")
    monkeypatch.setenv("LAYERSENSE_RENDER_JOB_MAX_WAIT_SECONDS", "30")

    from layersense_controller.config import Settings

    parsed = Settings()

    assert str(parsed.redis_url) == "redis://redis:6379/0"
    assert parsed.render_job_ttl_seconds == 7200
    assert parsed.render_job_wait_seconds == 20
    assert parsed.render_job_max_wait_seconds == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/unit/test_main.py::test_settings_expose_redis_and_long_poll_fields -v`
Expected: FAIL because `Settings` does not yet define the Redis/long-poll fields.

- [ ] **Step 3: Write the minimal config and broker implementation**

Update `layersense_controller/src/layersense_controller/config.py` to include:

```python
from pathlib import Path

from pydantic import AnyUrl
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    scenes_dir: Path = Path("./layersense_artifacts/code")
    artifacts_dir: Path = Path("./layersense_artifacts")
    host: str = "0.0.0.0"
    port: int = 8001
    redis_url: AnyUrl = AnyUrl("redis://localhost:6379/0")
    render_job_ttl_seconds: int = 86400
    render_job_wait_seconds: int = 20
    render_job_max_wait_seconds: int = 30

    model_config = {"env_prefix": "LAYERSENSE_"}


settings = Settings()
```

Create `layersense_controller/src/layersense_controller/broker.py` with:

```python
from functools import lru_cache

from redis import asyncio as redis_asyncio
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from layersense_controller.config import settings


broker = RedisStreamBroker(url=str(settings.redis_url)).with_result_backend(
    RedisAsyncResultBackend(redis_url=str(settings.redis_url))
)

@lru_cache
def create_redis_client() -> redis_asyncio.Redis:
    return redis_asyncio.from_url(str(settings.redis_url), decode_responses=True)
```

Add this note directly below the broker snippet in the implementation pass:

```python
# Keep runtime access behind cached accessor functions so tests can monkeypatch
# accessors instead of relying on module reload to refresh import-time singletons.
```

Update `layersense_controller/pyproject.toml` dependencies to include the new runtime packages:

```toml
dependencies = [
    "watchdog==6.0.0",
    "httpx==0.28.1",
    "pydantic==2.12.5",
    "pydantic-settings==2.10.1",
    "manim==0.20.1",
    "fastapi[standard]",
    "uvicorn",
    "redis[hiredis]",
    "taskiq",
    "taskiq-redis",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/unit/test_main.py::test_settings_expose_redis_and_long_poll_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_controller/pyproject.toml layersense_controller/src/layersense_controller/config.py layersense_controller/src/layersense_controller/broker.py layersense_controller/tests/unit/test_main.py
git commit -m "build: add controller redis and taskiq runtime config"
```

## Task 2: Redis-Backed Render Job Store

**Files:**
- Create: `layersense_controller/src/layersense_controller/render_jobs.py`
- Modify: `layersense_controller/src/layersense_controller/broker.py`
- Test: `layersense_controller/tests/unit/test_render_jobs.py`

- [ ] **Step 1: Write the failing job-store tests**

Create `layersense_controller/tests/unit/test_render_jobs.py` with:

```python
import pytest

from layersense_controller.render_jobs import RenderJobSnapshot, RenderJobStore

pytestmark = [pytest.mark.unit, pytest.mark.ai]


class FakePubSub:
    def __init__(self, messages: list[dict[str, str]] | None = None) -> None:
        self._messages = messages or []

    async def subscribe(self, *_args: str) -> None:
        return None

    async def unsubscribe(self, *_args: str) -> None:
        return None

    async def get_message(self, **_kwargs: object) -> dict[str, str] | None:
        if self._messages:
            return self._messages.pop(0)
        return None


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []
        self.pubsub_instance = FakePubSub()

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def publish(self, channel: str, message: str) -> None:
        self.published.append((channel, message))

    def pubsub(self) -> FakePubSub:
        return self.pubsub_instance


@pytest.mark.asyncio
async def test_create_queued_job_persists_snapshot_and_version() -> None:
    redis = FakeRedis()
    store = RenderJobStore(redis, ttl_seconds=3600)

    job = await store.create_queued_job(job_id="job-1", conversation_id="conv-1")

    assert job == RenderJobSnapshot(
        job_id="job-1",
        conversation_id="conv-1",
        status="queued",
        version=1,
        preview_url=None,
        final_url=None,
        error=None,
        stderr=None,
    )


@pytest.mark.asyncio
async def test_mark_succeeded_publishes_notification() -> None:
    redis = FakeRedis()
    store = RenderJobStore(redis, ttl_seconds=3600)
    await store.create_queued_job(job_id="job-1", conversation_id="conv-1")

    job = await store.update_job(
        job_id="job-1",
        status="succeeded",
        preview_url="/artifacts/by-hash/hash/preview",
        final_url="/artifacts/by-hash/hash/final",
    )

    assert job.version == 2
    assert redis.published == [("layersense:render-jobs:job-1:events", "2")]


@pytest.mark.asyncio
async def test_wait_for_newer_version_returns_current_snapshot_after_pubsub_message() -> None:
    redis = FakeRedis()
    redis.pubsub_instance = FakePubSub(messages=[{"data": "2"}])
    store = RenderJobStore(redis, ttl_seconds=3600)
    await store.create_queued_job(job_id="job-1", conversation_id="conv-1")
    await store.update_job(job_id="job-1", status="preview_rendering")

    job = await store.wait_for_newer_version(job_id="job-1", after_version=1, wait_seconds=1)

    assert job.version == 2
    assert job.status == "preview_rendering"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/unit/test_render_jobs.py -v`
Expected: FAIL because `render_jobs.py` does not exist yet.

- [ ] **Step 3: Write the minimal job-store implementation**

Create `layersense_controller/src/layersense_controller/render_jobs.py` with:

```python
import asyncio
from typing import Literal

from pydantic import BaseModel


RenderJobStatus = Literal[
    "queued",
    "preview_rendering",
    "waiting_for_final",
    "final_rendering",
    "succeeded",
    "failed",
]


class RenderJobSnapshot(BaseModel):
    job_id: str
    conversation_id: str
    status: RenderJobStatus
    version: int
    preview_url: str | None
    final_url: str | None
    error: str | None
    stderr: str | None


class RenderJobStore:
    def __init__(self, redis_client, ttl_seconds: int) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    def _job_key(self, job_id: str) -> str:
        return f"layersense:render-jobs:{job_id}"

    def _channel(self, job_id: str) -> str:
        return f"layersense:render-jobs:{job_id}:events"

    async def get_job(self, job_id: str) -> RenderJobSnapshot | None:
        raw = await self._redis.get(self._job_key(job_id))
        if raw is None:
            return None
        return RenderJobSnapshot.model_validate_json(raw)

    async def _save(self, snapshot: RenderJobSnapshot) -> RenderJobSnapshot:
        await self._redis.set(
            self._job_key(snapshot.job_id),
            snapshot.model_dump_json(),
            ex=self._ttl_seconds,
        )
        return snapshot

    async def create_queued_job(self, job_id: str, conversation_id: str) -> RenderJobSnapshot:
        return await self._save(
            RenderJobSnapshot(
                job_id=job_id,
                conversation_id=conversation_id,
                status="queued",
                version=1,
                preview_url=None,
                final_url=None,
                error=None,
                stderr=None,
            )
        )

    async def create_completed_job(
        self, job_id: str, conversation_id: str, preview_url: str, final_url: str
    ) -> RenderJobSnapshot:
        return await self._save(
            RenderJobSnapshot(
                job_id=job_id,
                conversation_id=conversation_id,
                status="succeeded",
                version=1,
                preview_url=preview_url,
                final_url=final_url,
                error=None,
                stderr=None,
            )
        )

    async def update_job(self, job_id: str, status: RenderJobStatus, **changes: str | None) -> RenderJobSnapshot:
        current = await self.get_job(job_id)
        if current is None:
            raise KeyError(job_id)
        next_snapshot = current.model_copy(
            update={
                "status": status,
                "version": current.version + 1,
                "preview_url": changes.get("preview_url", current.preview_url),
                "final_url": changes.get("final_url", current.final_url),
                "error": changes.get("error", current.error),
                "stderr": changes.get("stderr", current.stderr),
            }
        )
        await self._save(next_snapshot)
        await self._redis.publish(self._channel(job_id), str(next_snapshot.version))
        return next_snapshot

    async def wait_for_newer_version(
        self, job_id: str, after_version: int | None, wait_seconds: int
    ) -> RenderJobSnapshot | None:
        current = await self.get_job(job_id)
        if current is None:
            return None
        if after_version is None or current.version > after_version:
            return current

        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel(job_id))
        deadline = asyncio.get_running_loop().time() + wait_seconds
        try:
            while asyncio.get_running_loop().time() < deadline:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is not None:
                    break
            return await self.get_job(job_id)
        finally:
            await pubsub.unsubscribe(self._channel(job_id))
```

Then update `layersense_controller/src/layersense_controller/broker.py` once `RenderJobStore` exists:

```python
from layersense_controller.render_jobs import RenderJobStore


@lru_cache
def get_job_store() -> RenderJobStore:
    return RenderJobStore(create_redis_client(), ttl_seconds=settings.render_job_ttl_seconds)
```

This accessor replaces duplicated module-level `RenderJobStore(...)` instantiation in router and worker modules.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/unit/test_render_jobs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_controller/src/layersense_controller/render_jobs.py layersense_controller/tests/unit/test_render_jobs.py
git commit -m "feat: add redis-backed render job store"
```

## Task 3: Job-Based Controller Routes

**Files:**
- Create: `layersense_controller/src/layersense_controller/render_runtime.py`
- Modify: `layersense_controller/src/layersense_controller/router.py`
- Modify: `layersense_controller/tests/unit/test_router.py`
- Delete: `layersense_controller/src/layersense_controller/websocket_manager.py`
- Delete: `layersense_controller/tests/unit/test_websocket_manager.py`

- [ ] **Step 1: Write the failing router tests**

Add these tests to `layersense_controller/tests/unit/test_router.py`:

```python
def test_render_returns_job_snapshot_for_cached_scene(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "demo_scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    preview = artifacts_dir / "scenes" / "_root" / "preview" / "demo_scene_preview.mp4"
    final = artifacts_dir / "scenes" / "_root" / "final" / "demo_scene_final.mp4"
    preview.parent.mkdir(parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"preview")
    final.write_bytes(b"final")

    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps({
        "by_hash": {
            content_hash: {
                "scene_path": "demo_scene.py",
                "scene_uuid": "demo_scene",
                "preview": "_root/preview/demo_scene_preview.mp4",
                "final": "_root/final/demo_scene_final.mp4",
                "updated_at": "2026-04-24T00:00:00Z",
                "artifact_version": 1,
            }
        },
        "by_scene_uuid": {"demo_scene": content_hash},
    }))

    async def fake_create_completed_job(*, job_id: str, conversation_id: str, preview_url: str, final_url: str):
        return {
            "job_id": job_id,
            "conversation_id": conversation_id,
            "status": "succeeded",
            "version": 1,
            "preview_url": preview_url,
            "final_url": final_url,
            "error": None,
            "stderr": None,
        }

    monkeypatch.setattr("layersense_controller.router.create_job_id", lambda: "job-123")
    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"create_completed_job": fake_create_completed_job})(),
    )

    response = _build_client().post(
        "/render",
        json={"scene_path": str(scene_path), "conversation_id": "conv-1"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "job_id": "job-123",
        "job": {
            "job_id": "job-123",
            "conversation_id": "conv-1",
            "status": "succeeded",
            "version": 1,
            "preview_url": f"/artifacts/by-hash/{content_hash}/preview",
            "final_url": f"/artifacts/by-hash/{content_hash}/final",
            "error": None,
            "stderr": None,
        },
    }


def test_get_render_job_returns_404_for_unknown_job(monkeypatch) -> None:
    async def fake_wait_for_newer_version(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"wait_for_newer_version": fake_wait_for_newer_version})(),
    )

    response = _build_client().get("/render-jobs/job-missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Render job not found"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/unit/test_router.py::test_render_returns_job_snapshot_for_cached_scene layersense_controller/tests/unit/test_router.py::test_get_render_job_returns_404_for_unknown_job -v`
Expected: FAIL because the route contract is still websocket/background-task based.

- [ ] **Step 3: Write the minimal router implementation**

Create `layersense_controller/src/layersense_controller/render_runtime.py` with the shared helpers needed by both HTTP routes and worker code:

```python
from pathlib import Path
from typing import Literal

from layersense_controller.config import settings


def scene_uuid_from_scene_path(scene_path: Path) -> str:
    stem = scene_path.stem
    if stem.startswith("generated_"):
        generated_uuid = stem.removeprefix("generated_")
        if generated_uuid:
            return generated_uuid
    return stem


def is_generated_scene_path(scene_path: Path) -> bool:
    return scene_path.stem.startswith("generated_")


def artifact_url_by_hash(content_hash: str, kind: Literal["preview", "final"]) -> str:
    return f"/artifacts/by-hash/{content_hash}/{kind}"


def scene_relative_artifact_path(path: Path) -> str:
    scenes_root = (settings.artifacts_dir / "scenes").resolve()
    return path.resolve().relative_to(scenes_root).as_posix()
```

Update `layersense_controller/src/layersense_controller/router.py` so the route seam looks like this:

```python
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from layersense_controller.broker import get_job_store
from layersense_controller.cache import hash_file, lookup_cached_artifacts, store_cached_artifacts
from layersense_controller.config import settings
from layersense_controller.render import RenderError, _scene_path_relative_to_scenes_dir
from layersense_controller.render_jobs import RenderJobSnapshot
from layersense_controller.render_runtime import artifact_url_by_hash, is_generated_scene_path, scene_uuid_from_scene_path
from layersense_controller.render_tasks import run_render_job


def create_job_id() -> str:
    return uuid.uuid4().hex


class RenderQueueResponse(BaseModel):
    job_id: str
    job: RenderJobSnapshot


@router.post("/render")
async def render(request: RenderRequest) -> RenderQueueResponse:
    scene_path = Path(request.scene_path)
    if not scene_path.exists() or not scene_path.is_file():
        raise HTTPException(status_code=404, detail="Scene file not found")

    try:
        _scene_path_relative_to_scenes_dir(scene_path)
    except RenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content_hash = hash_file(scene_path)
    cached = lookup_cached_artifacts(content_hash)
    scene_uuid = scene_uuid_from_scene_path(scene_path)
    job_id = create_job_id()
    if cached and cached["preview"] and cached["final"] and (
        cached["scene_uuid"] == scene_uuid or is_generated_scene_path(scene_path)
    ):
        if cached["scene_uuid"] != scene_uuid:
            store_cached_artifacts(
                content_hash=content_hash,
                scene_uuid=scene_uuid,
                scene_path=scene_path.name,
                preview=cached["preview"],
                final=cached["final"],
            )
        job = await get_job_store().create_completed_job(
            job_id=job_id,
            conversation_id=request.conversation_id,
            preview_url=artifact_url_by_hash(content_hash, "preview"),
            final_url=artifact_url_by_hash(content_hash, "final"),
        )
        return RenderQueueResponse(job_id=job_id, job=job)

    job = await get_job_store().create_queued_job(job_id=job_id, conversation_id=request.conversation_id)
    await run_render_job.kiq(
        job_id=job_id,
        scene_path=str(scene_path),
        content_hash=content_hash,
        conversation_id=request.conversation_id,
    )
    return RenderQueueResponse(job_id=job_id, job=job)


@router.get("/render-jobs/{job_id}")
async def get_render_job(
    job_id: str,
    after_version: int | None = Query(default=None),
    wait_seconds: int | None = Query(default=None),
) -> dict:
    wait = min(wait_seconds or settings.render_job_wait_seconds, settings.render_job_max_wait_seconds)
    job = await get_job_store().wait_for_newer_version(job_id, after_version=after_version, wait_seconds=wait)
    if job is None:
        raise HTTPException(status_code=404, detail="Render job not found")
    return job.model_dump()
```

Delete the websocket endpoint and remove all `manager.broadcast(...)` calls from the file.

Preserve the current non-generated scene hash-collision behavior: when cached preview/final artifacts exist for a different `scene_uuid` and the current scene is not generated, `POST /render` must return a queued job and enqueue a fresh render instead of short-circuiting to completed.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/unit/test_router.py -v`
Expected: PASS for updated route contract; existing websocket assertions should be removed or rewritten before the full file passes.

- [ ] **Step 5: Commit**

```bash
git add layersense_controller/src/layersense_controller/router.py layersense_controller/tests/unit/test_router.py
git rm layersense_controller/src/layersense_controller/websocket_manager.py layersense_controller/tests/unit/test_websocket_manager.py
git commit -m "feat: switch controller routes to render job polling"
```

## Task 4: Taskiq Render Worker Pipeline

**Files:**
- Create: `layersense_controller/src/layersense_controller/render_tasks.py`
- Create: `layersense_controller/src/layersense_controller/worker.py`
- Create: `layersense_controller/tests/unit/test_render_tasks.py`

- [ ] **Step 1: Write the failing worker tests**

Create `layersense_controller/tests/unit/test_render_tasks.py` with:

```python
import pytest

from layersense_controller.render import RenderError
from layersense_controller.render_tasks import _run_render_pipeline

pytestmark = [pytest.mark.unit, pytest.mark.ai]


@pytest.mark.asyncio
async def test_run_render_pipeline_updates_preview_then_final(monkeypatch, tmp_path) -> None:
    scene_path = tmp_path / "layersense_scenes" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('demo')\n")
    preview_path = tmp_path / "artifacts" / "scenes" / "_root" / "preview" / "scene_preview.mp4"
    final_path = tmp_path / "artifacts" / "scenes" / "_root" / "final" / "scene_final.mp4"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    transitions: list[tuple[str, dict[str, str | None]]] = []

    async def fake_render_preview(_scene_path, _content_hash):
        preview_path.write_bytes(b"preview")
        return preview_path

    async def fake_render_final(_scene_path, _content_hash):
        final_path.write_bytes(b"final")
        return final_path

    async def fake_update_job(job_id: str, status: str, **changes: str | None):
        transitions.append((status, changes))
        return None

    monkeypatch.setattr("layersense_controller.render_tasks.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.render_tasks.render_final", fake_render_final)
    monkeypatch.setattr("layersense_controller.render_tasks.get_job_store", lambda: type("Store", (), {"update_job": fake_update_job})())
    monkeypatch.setattr(
        "layersense_controller.render_tasks.store_cached_artifacts",
        lambda **_kwargs: None,
    )

    await _run_render_pipeline(
        job_id="job-1",
        scene_path=scene_path,
        content_hash="hash-1",
        conversation_id="conv-1",
    )

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
async def test_run_render_pipeline_marks_failed_on_render_error(monkeypatch, tmp_path) -> None:
    scene_path = tmp_path / "layersense_scenes" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('demo')\n")

    transitions: list[tuple[str, dict[str, str | None]]] = []

    async def fake_render_preview(_scene_path, _content_hash):
        raise RenderError("manim exited with code 1", "stderr text")

    async def fake_update_job(job_id: str, status: str, **changes: str | None):
        transitions.append((status, changes))
        return None

    monkeypatch.setattr("layersense_controller.render_tasks.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.render_tasks.get_job_store", lambda: type("Store", (), {"update_job": fake_update_job})())

    await _run_render_pipeline(
        job_id="job-1",
        scene_path=scene_path,
        content_hash="hash-1",
        conversation_id="conv-1",
    )

    assert transitions[-1] == ("failed", {"error": "manim exited with code 1", "stderr": "stderr text"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-packages pytest layersense_controller/tests/unit/test_render_tasks.py -v`
Expected: FAIL because `render_tasks.py` does not exist.

- [ ] **Step 3: Write the minimal worker implementation**

Create `layersense_controller/src/layersense_controller/render_tasks.py` with:

```python
from pathlib import Path

from layersense_controller.broker import broker, get_job_store
from layersense_controller.cache import store_cached_artifacts
from layersense_controller.render import RenderError, render_final, render_preview
from layersense_controller.render_runtime import artifact_url_by_hash, scene_relative_artifact_path, scene_uuid_from_scene_path


async def _run_render_pipeline(
    job_id: str,
    scene_path: Path,
    content_hash: str,
    conversation_id: str,
) -> None:
    try:
        await get_job_store().update_job(job_id, "preview_rendering")
        preview_path = await render_preview(scene_path, content_hash)
        store_cached_artifacts(
            content_hash=content_hash,
            scene_uuid=scene_uuid_from_scene_path(scene_path),
            scene_path=scene_path.name,
            preview=scene_relative_artifact_path(preview_path),
        )
        await get_job_store().update_job(
            job_id,
            "waiting_for_final",
            preview_url=artifact_url_by_hash(content_hash, "preview"),
        )
        await get_job_store().update_job(job_id, "final_rendering")
        final_path = await render_final(scene_path, content_hash)
        store_cached_artifacts(
            content_hash=content_hash,
            scene_uuid=scene_uuid_from_scene_path(scene_path),
            scene_path=scene_path.name,
            final=scene_relative_artifact_path(final_path),
        )
        await get_job_store().update_job(
            job_id,
            "succeeded",
            preview_url=artifact_url_by_hash(content_hash, "preview"),
            final_url=artifact_url_by_hash(content_hash, "final"),
        )
    except RenderError as exc:
        await get_job_store().update_job(job_id, "failed", error=str(exc), stderr=exc.stderr)
    except Exception as exc:  # noqa: BLE001
        await get_job_store().update_job(job_id, "failed", error=str(exc), stderr="")


@broker.task
async def run_render_job(job_id: str, scene_path: str, content_hash: str, conversation_id: str) -> None:
    await _run_render_pipeline(
        job_id=job_id,
        scene_path=Path(scene_path),
        content_hash=content_hash,
        conversation_id=conversation_id,
    )
```

Create `layersense_controller/src/layersense_controller/worker.py` with:

```python
from layersense_controller.broker import broker
from layersense_controller import render_tasks  # noqa: F401

__all__ = ["broker"]
```

Do not import `router.py` from `render_tasks.py`. Shared helpers must come from `render_runtime.py` so the worker stays importable without a circular dependency.

Keep the current cache-index write path in this migration, but treat cross-container file locking over shared host volumes as a known local-dev limitation to document in Task 7 rather than solving it in this implementation pass.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-packages pytest layersense_controller/tests/unit/test_render_tasks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_controller/src/layersense_controller/render_tasks.py layersense_controller/src/layersense_controller/worker.py layersense_controller/tests/unit/test_render_tasks.py
git commit -m "feat: move render pipeline into taskiq worker"
```

## Task 5: Frontend API Types And Long-Poll Hook

**Files:**
- Modify: `layersense_frontend/src/types.ts`
- Modify: `layersense_frontend/src/api.ts`
- Modify: `layersense_frontend/src/api.test.ts`
- Create: `layersense_frontend/src/hooks/useRenderJob.ts`
- Create: `layersense_frontend/src/hooks/useRenderJob.test.ts`
- Delete: `layersense_frontend/src/hooks/useRenderEvents.ts`
- Delete: `layersense_frontend/src/hooks/useRenderEvents.test.ts`

- [ ] **Step 1: Write the failing frontend contract tests**

Update `layersense_frontend/src/api.test.ts` to assert:

```ts
it('queueRender posts to controller and returns a job snapshot', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
    new Response(
      JSON.stringify({
        job_id: 'job-123',
        job: {
          job_id: 'job-123',
          conversation_id: 'conv-123',
          status: 'queued',
          version: 1,
          preview_url: null,
          final_url: null,
          error: null,
          stderr: null,
        },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ),
  )

  const response = await queueRender({ scene_path: '/tmp/scene.py', conversation_id: 'conv-123' })

  expect(fetchMock).toHaveBeenCalledWith('http://localhost:8001/render', expect.any(Object))
  expect(response.job_id).toBe('job-123')
  expect(response.job.status).toBe('queued')
})


it('getRenderJob requests the controller job endpoint', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
    new Response(
      JSON.stringify({
        job_id: 'job-123',
        conversation_id: 'conv-123',
        status: 'waiting_for_final',
        version: 2,
        preview_url: '/artifacts/by-hash/hash/preview',
        final_url: null,
        error: null,
        stderr: null,
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ),
  )

  const response = await getRenderJob('job-123', { afterVersion: 1, waitSeconds: 20 })

  expect(fetchMock).toHaveBeenCalledWith(
    'http://localhost:8001/render-jobs/job-123?after_version=1&wait_seconds=20',
    { method: 'GET' },
  )
  expect(response.status).toBe('waiting_for_final')
})
```

Create `layersense_frontend/src/hooks/useRenderJob.test.ts` with:

```ts
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useRenderJob } from './useRenderJob'

const mockGetRenderJob = vi.fn()

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return { ...actual, getRenderJob: (...args: unknown[]) => mockGetRenderJob(...args) }
})

describe('useRenderJob', () => {
  afterEach(() => {
    mockGetRenderJob.mockReset()
  })

  it('polls with afterVersion and updates snapshot', async () => {
    mockGetRenderJob.mockResolvedValueOnce({
      job_id: 'job-1',
      conversation_id: 'conv-1',
      status: 'waiting_for_final',
      version: 2,
      preview_url: '/preview.mp4',
      final_url: null,
      error: null,
      stderr: null,
    })

    const { result } = renderHook(() =>
      useRenderJob({
        jobId: 'job-1',
        initialJob: {
          job_id: 'job-1',
          conversation_id: 'conv-1',
          status: 'queued',
          version: 1,
          preview_url: null,
          final_url: null,
          error: null,
          stderr: null,
        },
      }),
    )

    await waitFor(() => expect(result.current?.version).toBe(2))
    expect(mockGetRenderJob).toHaveBeenCalledWith('job-1', { afterVersion: 1, waitSeconds: 20 })
  })

  it('retries after a transient polling error', async () => {
    vi.useFakeTimers()
    mockGetRenderJob
      .mockRejectedValueOnce(new Error('temporary network error'))
      .mockResolvedValueOnce({
        job_id: 'job-1',
        conversation_id: 'conv-1',
        status: 'waiting_for_final',
        version: 2,
        preview_url: '/preview.mp4',
        final_url: null,
        error: null,
        stderr: null,
      })

    const { result } = renderHook(() =>
      useRenderJob({
        jobId: 'job-1',
        initialJob: {
          job_id: 'job-1',
          conversation_id: 'conv-1',
          status: 'queued',
          version: 1,
          preview_url: null,
          final_url: null,
          error: null,
          stderr: null,
        },
      }),
    )

    await vi.advanceTimersByTimeAsync(1000)
    await waitFor(() => expect(result.current?.version).toBe(2))
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bun run --cwd layersense_frontend test -- src/api.test.ts src/hooks/useRenderJob.test.ts`
Expected: FAIL because the new API types and hook do not exist.

- [ ] **Step 3: Write the minimal frontend API and hook**

Update `layersense_frontend/src/types.ts` with:

```ts
export type RenderJobStatus =
  | 'queued'
  | 'preview_rendering'
  | 'waiting_for_final'
  | 'final_rendering'
  | 'succeeded'
  | 'failed'

export type RenderJobSnapshot = {
  job_id: string
  conversation_id: string
  status: RenderJobStatus
  version: number
  preview_url: string | null
  final_url: string | null
  error: string | null
  stderr: string | null
}

export type RenderQueueResponse = {
  job_id: string
  job: RenderJobSnapshot
}
```

Update `layersense_frontend/src/api.ts` with:

```ts
export const getRenderJob = async (
  jobId: string,
  options: { afterVersion?: number; waitSeconds?: number } = {},
): Promise<RenderJobSnapshot> => {
  const params = new URLSearchParams()
  if (options.afterVersion !== undefined) params.set('after_version', String(options.afterVersion))
  if (options.waitSeconds !== undefined) params.set('wait_seconds', String(options.waitSeconds))
  const suffix = params.toString() ? `?${params.toString()}` : ''
  const url = `${CONTROLLER_BASE}/render-jobs/${jobId}${suffix}`
  const response = await fetch(url, { method: 'GET' })
  return parseJsonResponse<RenderJobSnapshot>(response, url)
}
```

Create `layersense_frontend/src/hooks/useRenderJob.ts` with:

```ts
import { useEffect, useState } from 'react'

import { getRenderJob } from '../api'
import type { RenderJobSnapshot } from '../types'

const POLL_RETRY_DELAY_MS = 1000

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

type UseRenderJobParams = {
  jobId: string | null
  initialJob: RenderJobSnapshot | null
}

export const useRenderJob = ({ jobId, initialJob }: UseRenderJobParams): RenderJobSnapshot | null => {
  const [job, setJob] = useState<RenderJobSnapshot | null>(initialJob)

  useEffect(() => {
    setJob(initialJob)
  }, [initialJob])

  useEffect(() => {
    if (!jobId || !initialJob) return

    let cancelled = false

    void (async () => {
      let current = initialJob
      while (!cancelled && current.status !== 'succeeded' && current.status !== 'failed') {
        try {
          const next = await getRenderJob(jobId, { afterVersion: current.version, waitSeconds: 20 })
          if (cancelled) return
          current = next
          setJob(next)
        } catch {
          if (cancelled) return
          await sleep(POLL_RETRY_DELAY_MS)
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [jobId, initialJob])

  return job
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bun run --cwd layersense_frontend test -- src/api.test.ts src/hooks/useRenderJob.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_frontend/src/types.ts layersense_frontend/src/api.ts layersense_frontend/src/api.test.ts layersense_frontend/src/hooks/useRenderJob.ts layersense_frontend/src/hooks/useRenderJob.test.ts
git rm layersense_frontend/src/hooks/useRenderEvents.ts layersense_frontend/src/hooks/useRenderEvents.test.ts
git commit -m "feat: add frontend render job polling client"
```

## Task 6: Frontend App Flow Migration

**Files:**
- Modify: `layersense_frontend/src/App.tsx`
- Modify: `layersense_frontend/src/App.test.tsx`
- Modify: `layersense_frontend/src/components/VideoPlayer.tsx`

- [ ] **Step 1: Write the failing App tests**

Update `layersense_frontend/src/App.test.tsx` so the core flow is driven by job snapshots instead of websocket callbacks:

```ts
it('shows preview then final as polled job snapshots advance', async () => {
  mockCreateAnimation.mockResolvedValue({ conversation_id: 'conv-1', scene_path: '/tmp/scene.py' })
  mockQueueRender.mockResolvedValue({
    job_id: 'job-1',
    job: {
      job_id: 'job-1',
      conversation_id: 'conv-1',
      status: 'queued',
      version: 1,
      preview_url: null,
      final_url: null,
      error: null,
      stderr: null,
    },
  })
  mockUseRenderJob
    .mockReturnValueOnce({
      job_id: 'job-1',
      conversation_id: 'conv-1',
      status: 'waiting_for_final',
      version: 2,
      preview_url: '/preview.mp4',
      final_url: null,
      error: null,
      stderr: null,
    })
    .mockReturnValueOnce({
      job_id: 'job-1',
      conversation_id: 'conv-1',
      status: 'succeeded',
      version: 3,
      preview_url: '/preview.mp4',
      final_url: '/final.mp4',
      error: null,
      stderr: null,
    })

  const { getByRole, getByTestId, rerender } = render(<App />)
  fireEvent.click(getByRole('button', { name: 'Generate' }))

  await waitFor(() => {
    const preview = getByTestId('render-video') as HTMLVideoElement
    expect(preview.getAttribute('src')).toBe(`${CONTROLLER_BASE}/preview.mp4`)
  })

  rerender(<App />)
  await waitFor(() => {
    const final = getByTestId('render-video') as HTMLVideoElement
    expect(final.getAttribute('src')).toBe(`${CONTROLLER_BASE}/final.mp4`)
  })
})


it('shows failed job errors', async () => {
  mockCreateAnimation.mockResolvedValue({ conversation_id: 'conv-1', scene_path: '/tmp/scene.py' })
  mockQueueRender.mockResolvedValue({
    job_id: 'job-1',
    job: {
      job_id: 'job-1',
      conversation_id: 'conv-1',
      status: 'failed',
      version: 2,
      preview_url: null,
      final_url: null,
      error: 'render exploded',
      stderr: '',
    },
  })
  mockUseRenderJob.mockReturnValue({
    job_id: 'job-1',
    conversation_id: 'conv-1',
    status: 'failed',
    version: 2,
    preview_url: null,
    final_url: null,
    error: 'render exploded',
    stderr: '',
  })

  const { getByRole, getByText } = render(<App />)
  fireEvent.click(getByRole('button', { name: 'Generate' }))

  await waitFor(() => expect(getByText('render exploded')).toBeTruthy())
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bun run --cwd layersense_frontend test -- src/App.test.tsx`
Expected: FAIL because `App.tsx` still depends on websocket callbacks.

- [ ] **Step 3: Write the minimal App migration**

Update `layersense_frontend/src/App.tsx` to follow this shape:

```ts
import { useEffect, useRef, useState } from 'react'

import { CONTROLLER_BASE, createAnimation, queueRender } from './api'
import { useRenderJob } from './hooks/useRenderJob'
import type { RenderJobSnapshot } from './types'

function App() {
  const [jobId, setJobId] = useState<string | null>(null)
  const [initialJob, setInitialJob] = useState<RenderJobSnapshot | null>(null)
  const currentJob = useRenderJob({ jobId, initialJob })

  useEffect(() => {
    if (!currentJob) return
    setPreviewUrl(currentJob.preview_url ? normalizeArtifactUrl(currentJob.preview_url) : null)
    setFinalUrl(currentJob.final_url ? normalizeArtifactUrl(currentJob.final_url) : null)
    setError(currentJob.error)

    if (currentJob.status === 'failed') {
      setStatus('error')
    } else if (currentJob.final_url) {
      setStatus('complete')
    } else if (currentJob.preview_url) {
      setStatus('waiting_for_final')
    } else {
      setStatus('waiting_for_preview')
    }
  }, [currentJob])

  const handleGenerate = useCallback(async () => {
    setError(null)
    setPreviewUrl(null)
    setFinalUrl(null)
    setJobId(null)
    setInitialJob(null)
    setStatus('submitting_to_agent')

    const snapshot = canvasRef.current?.getSceneSnapshot() ?? {
      elements: [],
      appState: {},
      files: {},
    }

    const animation = await createAnimation({ prompt, scene: snapshot })
    setConversationId(animation.conversation_id)
    setStatus('queueing_render')
    const renderResponse = await queueRender({ scene_path: animation.scene_path, conversation_id: animation.conversation_id })
    setJobId(renderResponse.job_id)
    setInitialJob(renderResponse.job)
    setStatus(renderResponse.job.preview_url ? 'waiting_for_final' : 'waiting_for_preview')
  }, [prompt])
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bun run --cwd layersense_frontend test -- src/App.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add layersense_frontend/src/App.tsx layersense_frontend/src/App.test.tsx layersense_frontend/src/components/VideoPlayer.tsx
git commit -m "feat: drive frontend render state from polled jobs"
```

## Task 7: Docker, E2E, And Documentation Alignment

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.e2e.yml`
- Modify: `layersense_controller/Dockerfile`
- Modify: `scripts/run_e2e.sh`
- Modify: `tests/e2e/test_dev_stack_e2e.py`
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Write the failing e2e/helper updates**

Update `tests/e2e/test_dev_stack_e2e.py` so `_queue_render` and the polling helper expect the new contract:

```python
def _queue_render(scene_path: str, conversation_id: str) -> dict[str, Any]:
    response = _request_with_boundary_failure(
        "POST",
        urljoin(_controller_base(), "/render"),
        "controller render request",
        {"scene_path": scene_path, "conversation_id": conversation_id},
    )
    _assert_ok(response, "controller render request")

    body = response.json()
    assert "job_id" in body, f"controller render returned unexpected body: {body}"
    assert "job" in body, f"controller render returned unexpected body: {body}"
    return body


def _wait_for_render_job(job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + RENDER_TIMEOUT_SECONDS
    version = None
    last_job = None
    while time.monotonic() < deadline:
        params = {}
        if version is not None:
            params["after_version"] = version
            params["wait_seconds"] = 5
        response = requests.get(
            urljoin(_controller_base(), f"/render-jobs/{job_id}"),
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS + 5,
        )
        _assert_ok(response, "controller render job request")
        last_job = response.json()
        version = last_job["version"]
        if last_job["status"] in {"succeeded", "failed"}:
            return last_job
    pytest.fail(f"render job {job_id} did not reach a terminal state; last_job={last_job}")
```

- [ ] **Step 2: Run the targeted e2e file to verify it fails**

Run: `uv run --all-packages pytest tests/e2e/test_dev_stack_e2e.py -m e2e -v`
Expected: FAIL until the controller, compose, and worker changes are all in place.

- [ ] **Step 3: Write the compose, script, and doc updates**

Update `docker-compose.yml` services to include:

```yaml
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  controller:
    environment:
      LAYERSENSE_REDIS_URL: redis://redis:6379/0
    depends_on:
      - redis

  controller-worker:
    build:
      context: ./layersense_controller
    command: ["taskiq", "worker", "layersense_controller.worker:broker"]
    environment:
      LAYERSENSE_SCENES_DIR: /layersense_artifacts/code
      LAYERSENSE_ARTIFACTS_DIR: /layersense_artifacts
      LAYERSENSE_REDIS_URL: redis://redis:6379/0
    depends_on:
      - redis
    volumes:
      - ./layersense_artifacts/code:/layersense_artifacts/code
      - ./layersense_artifacts:/layersense_artifacts
```

Update `scripts/run_e2e.sh` by removing the websocket export and adding Redis readiness if needed:

```sh
wait_for_http "http://controller:8001/health" "controller health"

export LAYERSENSE_E2E_FRONTEND_BASE="http://frontend"
export LAYERSENSE_E2E_AGENT_BASE="http://agent:8000"
export LAYERSENSE_E2E_CONTROLLER_BASE="http://controller:8001"
export LAYERSENSE_E2E_REPO_ROOT="${workspace_root}"
```

Update `README.md`, `docs/ROADMAP.md`, and `AGENTS.md` to replace current-flow wording like:

```md
Frontend explicitly queues a render with `layersense_controller`, receives a `job_id`, then long-polls `GET /render-jobs/{job_id}` for preview/final status while the Taskiq worker renders in the background.
```

Also add a short current-limitations note to the same docs:

```md
The cache index still uses file-based locking. In local Docker Desktop environments with shared host volumes, cache-index contention may remain a known limitation until a Redis-backed cache-lock follow-up lands.
```

- [ ] **Step 4: Run verification to confirm the migration works end-to-end**

Run in order:

1. `just lint`
Expected: PASS

2. `just test`
Expected: PASS

3. `just test-e2e`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml docker-compose.e2e.yml layersense_controller/Dockerfile scripts/run_e2e.sh tests/e2e/test_dev_stack_e2e.py README.md docs/ROADMAP.md AGENTS.md
git commit -m "feat: ship redis-backed long-poll render flow"
```
