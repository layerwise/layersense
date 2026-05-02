import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from layersense_controller.cache import hash_render_request
from layersense_controller.config import settings
from layersense_controller.render_jobs import RenderJobSnapshot
from layersense_controller.router import RenderRequest, router

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _request_hash(scene_path: Path, background_color: str | None = None) -> str:
    render_options = {"background_color": background_color}
    return hash_render_request(scene_path, render_options)


def test_health() -> None:
    response = _build_client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_render_request_accepts_background_color() -> None:
    request = RenderRequest.model_validate(
        {
            "scene_path": "/tmp/generated_123.py",
            "conversation_id": "conversation-123",
            "render_options": {"background_color": "#112233"},
        }
    )

    assert request.render_options.background_color == "#112233"


def test_render_returns_404_for_missing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path / "artifacts")
    missing_path = tmp_path / "missing_scene.py"

    response = _build_client().post(
        "/render",
        json={"scene_path": str(missing_path), "conversation_id": "conv-1"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Scene file not found"


def test_render_returns_404_for_directory_path(tmp_path) -> None:
    directory_path = tmp_path / "scene_dir"
    directory_path.mkdir()

    response = _build_client().post(
        "/render",
        json={"scene_path": str(directory_path), "conversation_id": "conv-1"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Scene file not found"


def test_render_returns_400_for_scene_outside_configured_scenes_dir(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    scenes_dir.mkdir()
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    off_root_scene = tmp_path / "outside.py"
    off_root_scene.write_text("print('outside')\n")

    response = _build_client().post(
        "/render",
        json={"scene_path": str(off_root_scene), "conversation_id": "conv-1"},
    )

    assert response.status_code == 400
    assert "configured scenes_dir" in response.json()["detail"]


def test_render_cache_identity_changes_when_background_color_changes(
    tmp_path, monkeypatch
) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "generated_123.py"
    scene_path.write_text(
        "from manim import Scene\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n"
    )

    queued_jobs: list[dict[str, str]] = []
    enqueued_jobs: list[dict[str, object]] = []

    async def fake_create_queued_job(self, *, job_id: str, conversation_id: str):
        queued_jobs.append({"job_id": job_id, "conversation_id": conversation_id})
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

    async def fake_enqueue_render_job(**kwargs: object) -> None:
        enqueued_jobs.append(kwargs)

    job_ids = iter(["job-1", "job-2"])
    monkeypatch.setattr("layersense_controller.router.create_job_id", lambda: next(job_ids))
    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"create_queued_job": fake_create_queued_job})(),
    )
    monkeypatch.setattr("layersense_controller.router.enqueue_render_job", fake_enqueue_render_job)

    client = _build_client()
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
    assert first.json()["job"]["status"] == "queued"
    assert second.json()["job"]["status"] == "queued"
    assert queued_jobs == [
        {"job_id": "job-1", "conversation_id": "conversation-1"},
        {"job_id": "job-2", "conversation_id": "conversation-2"},
    ]
    assert enqueued_jobs == [
        {
            "job_id": "job-1",
            "scene_path": str(scene_path),
            "content_hash": _request_hash(scene_path, background_color="#000000"),
            "conversation_id": "conversation-1",
            "render_options": RenderRequest.model_validate(
                {
                    "scene_path": str(scene_path),
                    "conversation_id": "conversation-1",
                    "render_options": {"background_color": "#000000"},
                }
            ).render_options,
        },
        {
            "job_id": "job-2",
            "scene_path": str(scene_path),
            "content_hash": _request_hash(scene_path, background_color="#ffffff"),
            "conversation_id": "conversation-2",
            "render_options": RenderRequest.model_validate(
                {
                    "scene_path": str(scene_path),
                    "conversation_id": "conversation-2",
                    "render_options": {"background_color": "#ffffff"},
                }
            ).render_options,
        },
    ]


def test_render_threads_render_options_through_queued_pipeline(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "generated_123.py"
    scene_path.write_text(
        "from manim import Scene\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n"
    )
    content_hash = _request_hash(scene_path, background_color="#112233")

    queued_jobs: list[dict[str, str]] = []
    enqueued_jobs: list[dict[str, object]] = []

    async def fake_create_queued_job(self, *, job_id: str, conversation_id: str):
        queued_jobs.append({"job_id": job_id, "conversation_id": conversation_id})
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

    async def fake_enqueue_render_job(**kwargs: object) -> None:
        enqueued_jobs.append(kwargs)

    monkeypatch.setattr("layersense_controller.router.create_job_id", lambda: "job-1")
    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"create_queued_job": fake_create_queued_job})(),
    )
    monkeypatch.setattr("layersense_controller.router.enqueue_render_job", fake_enqueue_render_job)

    response = _build_client().post(
        "/render",
        json={
            "scene_path": str(scene_path),
            "conversation_id": "conversation-1",
            "render_options": {"background_color": "#112233"},
        },
    )

    assert response.status_code == 200
    assert response.json()["job"]["status"] == "queued"
    assert queued_jobs == [{"job_id": "job-1", "conversation_id": "conversation-1"}]
    assert enqueued_jobs[0]["content_hash"] == content_hash
    assert enqueued_jobs[0]["render_options"].background_color == "#112233"


def test_render_returns_job_snapshot_for_cached_scene(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "demo_scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = _request_hash(scene_path)
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
                        "updated_at": "2026-04-24T00:00:00Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"demo_scene": content_hash},
            }
        )
    )

    async def fake_create_completed_job(
        self, *, job_id: str, conversation_id: str, preview_url: str, final_url: str
    ):
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


def test_render_skips_cached_fast_path_when_index_points_to_missing_files(
    tmp_path, monkeypatch
) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "demo_scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = _request_hash(scene_path)
    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    content_hash: {
                        "scene_path": "demo_scene.py",
                        "scene_uuid": "demo_scene",
                        "preview": "_root/preview/missing_preview.mp4",
                        "final": "_root/final/missing_final.mp4",
                        "updated_at": "2026-04-24T00:00:00Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"demo_scene": content_hash},
            }
        )
    )

    async def fake_create_queued_job(self, *, job_id: str, conversation_id: str):
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

    enqueued_jobs: list[dict[str, object]] = []

    async def fake_enqueue_render_job(**kwargs: object) -> None:
        enqueued_jobs.append(kwargs)

    monkeypatch.setattr("layersense_controller.router.create_job_id", lambda: "job-123")
    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"create_queued_job": fake_create_queued_job})(),
    )
    monkeypatch.setattr("layersense_controller.router.enqueue_render_job", fake_enqueue_render_job)

    response = _build_client().post(
        "/render",
        json={"scene_path": str(scene_path), "conversation_id": "conv-1"},
    )

    assert response.status_code == 200
    assert response.json()["job"]["status"] == "queued"
    assert enqueued_jobs == [
        {
            "job_id": "job-123",
            "scene_path": str(scene_path),
            "content_hash": content_hash,
            "conversation_id": "conv-1",
            "render_options": RenderRequest.model_validate(
                {"scene_path": str(scene_path), "conversation_id": "conv-1"}
            ).render_options,
        }
    ]


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


def test_get_render_job_clamps_excessive_wait_seconds(monkeypatch) -> None:
    calls: list[tuple[int | None, int]] = []

    async def fake_wait_for_newer_version(
        self, job_id: str, after_version: int | None, wait_seconds: int
    ):
        calls.append((after_version, wait_seconds))
        return RenderJobSnapshot(
            job_id=job_id,
            conversation_id="conv-1",
            status="queued",
            version=1,
            preview_url=None,
            final_url=None,
            error=None,
            stderr=None,
        )

    monkeypatch.setattr(settings, "render_job_wait_seconds", 20)
    monkeypatch.setattr(settings, "render_job_max_wait_seconds", 30)
    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"wait_for_newer_version": fake_wait_for_newer_version})(),
    )

    response = _build_client().get("/render-jobs/job-1?after_version=1&wait_seconds=999")

    assert response.status_code == 200
    assert calls == [(1, 30)]


def test_get_render_job_replaces_negative_wait_seconds_with_default(monkeypatch) -> None:
    calls: list[int] = []

    async def fake_wait_for_newer_version(
        self, job_id: str, after_version: int | None, wait_seconds: int
    ):
        del after_version
        calls.append(wait_seconds)
        return RenderJobSnapshot(
            job_id=job_id,
            conversation_id="conv-1",
            status="queued",
            version=1,
            preview_url=None,
            final_url=None,
            error=None,
            stderr=None,
        )

    monkeypatch.setattr(settings, "render_job_wait_seconds", 20)
    monkeypatch.setattr(settings, "render_job_max_wait_seconds", 30)
    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"wait_for_newer_version": fake_wait_for_newer_version})(),
    )

    response = _build_client().get("/render-jobs/job-1?wait_seconds=-5")

    assert response.status_code == 200
    assert calls == [20]


def test_artifact_returns_404_for_directory(tmp_path, monkeypatch) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    (artifacts_dir / "dir.mp4").mkdir()

    response = _build_client().get("/artifacts/dir.mp4")

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact not found"


def test_artifact_serves_nested_scene_path(tmp_path, monkeypatch) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifact_path = artifacts_dir / "scenes" / "demo" / "preview" / "scene_preview.mp4"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"preview")
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    response = _build_client().get("/artifacts/scenes/demo/preview/scene_preview.mp4")

    assert response.status_code == 200
    assert response.content == b"preview"


def test_artifact_rejects_non_scene_files(tmp_path, monkeypatch) -> None:
    artifacts_dir = tmp_path / "artifacts"
    cache_index = artifacts_dir / "cache" / "index.json"
    cache_index.parent.mkdir(parents=True)
    cache_index.write_text("{}")
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    response = _build_client().get("/artifacts/cache/index.json")

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact not found"


def test_artifact_by_hash_serves_preview(tmp_path, monkeypatch) -> None:
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    preview_path = artifacts_dir / "scenes" / "demo" / "preview" / "scene_preview.mp4"
    preview_path.parent.mkdir(parents=True)
    preview_path.write_bytes(b"preview")
    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    "hash-1": {
                        "scene_path": "code/generated_scene-123.py",
                        "scene_uuid": "scene-123",
                        "preview": "demo/preview/scene_preview.mp4",
                        "final": None,
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"scene-123": "hash-1"},
            }
        )
    )

    response = _build_client().get("/artifacts/by-hash/hash-1/preview")

    assert response.status_code == 200
    assert response.content == b"preview"


def test_artifact_scene_route_prefers_final_and_falls_back_to_preview(
    tmp_path, monkeypatch
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    preview_path = artifacts_dir / "scenes" / "demo" / "preview" / "scene_preview.mp4"
    final_path = artifacts_dir / "scenes" / "demo" / "final" / "scene_final.mp4"
    preview_path.parent.mkdir(parents=True)
    final_path.parent.mkdir(parents=True)
    preview_path.write_bytes(b"preview")
    final_path.write_bytes(b"final")
    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    "hash-1": {
                        "scene_path": "code/generated_scene-123.py",
                        "scene_uuid": "scene-123",
                        "preview": "demo/preview/scene_preview.mp4",
                        "final": "demo/final/scene_final.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"scene-123": "hash-1"},
            }
        )
    )

    client = _build_client()

    response = client.get("/artifacts/scenes/scene-123")
    assert response.status_code == 200
    assert response.content == b"final"

    final_path.unlink()
    response = client.get("/artifacts/scenes/scene-123")
    assert response.status_code == 200
    assert response.content == b"preview"

    response = client.get("/artifacts/scenes/scene-123?preview=true")
    assert response.status_code == 200
    assert response.content == b"preview"


def test_artifact_scene_route_uses_generated_filename_stem_as_scene_uuid(
    tmp_path, monkeypatch
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    final_path = artifacts_dir / "scenes" / "demo" / "final" / "scene_final.mp4"
    final_path.parent.mkdir(parents=True)
    final_path.write_bytes(b"final")
    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    "hash-1": {
                        "scene_path": "code/generated_123e4567.py",
                        "scene_uuid": "123e4567",
                        "preview": None,
                        "final": "demo/final/scene_final.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"123e4567": "hash-1"},
            }
        )
    )

    response = _build_client().get("/artifacts/scenes/123e4567")

    assert response.status_code == 200
    assert response.content == b"final"


def test_render_reuses_full_cached_hash_for_different_generated_scene_uuid(
    tmp_path, monkeypatch
) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "generated_new-scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = _request_hash(scene_path)
    preview = artifacts_dir / "scenes" / "_root" / "preview" / "generated_new-scene_preview.mp4"
    final = artifacts_dir / "scenes" / "_root" / "final" / "generated_new-scene_final.mp4"
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
                        "scene_path": "generated_old-scene.py",
                        "scene_uuid": "old-scene",
                        "preview": "_root/preview/generated_new-scene_preview.mp4",
                        "final": "_root/final/generated_new-scene_final.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"old-scene": content_hash},
            }
        )
    )

    async def fake_create_completed_job(
        self, *, job_id: str, conversation_id: str, preview_url: str, final_url: str
    ):
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

    monkeypatch.setattr("layersense_controller.router.create_job_id", lambda: "job-generated")
    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"create_completed_job": fake_create_completed_job})(),
    )

    response = _build_client().post(
        "/render",
        json={"scene_path": str(scene_path), "conversation_id": "conv-reuse-generated"},
    )

    assert response.status_code == 200
    assert response.json()["job"]["status"] == "succeeded"

    scene_response = _build_client().get("/artifacts/scenes/new-scene")
    assert scene_response.status_code == 200
    assert scene_response.content == b"final"


def test_render_treats_non_generated_scene_with_index_entry_as_uncached(
    tmp_path, monkeypatch
) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    (scenes_dir / "algebra").mkdir(parents=True)
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "algebra" / "demo_scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = _request_hash(scene_path)
    preview = artifacts_dir / "scenes" / "algebra" / "preview" / "demo_scene_preview.mp4"
    final = artifacts_dir / "scenes" / "algebra" / "final" / "demo_scene_final.mp4"
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
                        "scene_path": "algebra/demo_scene.py",
                        "scene_uuid": "demo-scene-uuid",
                        "preview": "algebra/preview/demo_scene_preview.mp4",
                        "final": "algebra/final/demo_scene_final.mp4",
                        "updated_at": "2026-04-06T12:34:56Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"demo-scene-uuid": content_hash},
            }
        )
    )

    queued: list[dict[str, object]] = []

    async def fake_create_queued_job(self, *, job_id: str, conversation_id: str):
        queued.append({"job_id": job_id, "conversation_id": conversation_id})
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

    async def fake_enqueue_render_job(**kwargs: object) -> None:
        queued.append(kwargs)

    monkeypatch.setattr("layersense_controller.router.create_job_id", lambda: "job-manual")
    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"create_queued_job": fake_create_queued_job})(),
    )
    monkeypatch.setattr("layersense_controller.router.enqueue_render_job", fake_enqueue_render_job)

    response = _build_client().post(
        "/render",
        json={"scene_path": str(scene_path), "conversation_id": "conv-manual-scene"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "job_id": "job-manual",
        "job": {
            "job_id": "job-manual",
            "conversation_id": "conv-manual-scene",
            "status": "queued",
            "version": 1,
            "preview_url": None,
            "final_url": None,
            "error": None,
            "stderr": None,
        },
    }
    assert queued[-1] == {
        "job_id": "job-manual",
        "scene_path": str(scene_path),
        "content_hash": content_hash,
        "conversation_id": "conv-manual-scene",
        "render_options": RenderRequest.model_validate(
            {"scene_path": str(scene_path), "conversation_id": "conv-manual-scene"}
        ).render_options,
    }
