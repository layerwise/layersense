import json
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
    content_hash = hash_render_request(scene_path, {})

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

    async def fake_create_queued_job(
        self, *, job_id: str, conversation_id: str
    ) -> RenderJobSnapshot:
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
                "cli_flags": {"quality": "m", "renderer": "cairo"},
            },
        )

    expected_hash = hash_render_request(scene_path, {"quality": "m", "renderer": "cairo"})
    assert response.status_code == 200
    kiq_mock.assert_awaited_once_with(
        job_id="job-1",
        scene_path=str(scene_path),
        content_hash=expected_hash,
        conversation_id="conversation-1",
        cli_flags={"quality": "m", "renderer": "cairo"},
    )


def test_get_render_job_returns_404_when_store_has_no_job(monkeypatch) -> None:
    """Return 404 when the requested render job does not exist."""
    calls = []

    async def fake_wait_for_newer_version(self, job_id: str, after_version, wait_seconds: int):
        del self
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

    async def fake_wait_for_newer_version(self, job_id: str, after_version, wait_seconds: int):
        del self
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


def test_get_artifact_by_hash_serves_cached_preview_file(tmp_path, monkeypatch) -> None:
    """Serve a cached preview artifact through the by-hash route."""
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    preview = artifacts_dir / "scenes" / "_root" / "preview" / "demo_preview.mp4"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"preview")

    index_path = artifacts_dir / "cache" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "by_hash": {
                    "hash-1": {
                        "scene_path": "demo.py",
                        "scene_uuid": "demo",
                        "preview": "_root/preview/demo_preview.mp4",
                        "final": None,
                        "updated_at": "2026-05-04T00:00:00Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"demo": "hash-1"},
            }
        )
    )

    with _client() as client:
        response = client.get("/artifacts/by-hash/hash-1/preview")

    assert response.status_code == 200
    assert response.content == b"preview"


def test_get_artifact_for_scene_prefers_final_and_falls_back_to_preview(
    tmp_path, monkeypatch
) -> None:
    """Serve final scene artifacts when present and preview artifacts otherwise."""
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    preview = artifacts_dir / "scenes" / "_root" / "preview" / "demo_preview.mp4"
    final = artifacts_dir / "scenes" / "_root" / "final" / "demo_final.mp4"
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
                    "hash-1": {
                        "scene_path": "demo.py",
                        "scene_uuid": "demo",
                        "preview": "_root/preview/demo_preview.mp4",
                        "final": "_root/final/demo_final.mp4",
                        "updated_at": "2026-05-04T00:00:00Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"demo": "hash-1"},
            }
        )
    )

    with _client() as client:
        final_response = client.get("/artifacts/scenes/demo")
        preview_response = client.get("/artifacts/scenes/demo?preview=true")

    assert final_response.status_code == 200
    assert final_response.content == b"final"
    assert preview_response.status_code == 200
    assert preview_response.content == b"preview"


def test_render_generated_scene_reuses_cached_hash_and_remaps_scene_uuid(
    tmp_path, monkeypatch
) -> None:
    """Reuse cached generated-scene artifacts and remap the scene UUID when the file stem changed."""
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    scene_path = scenes_dir / "generated_new-uuid.py"
    scene_path.write_text("print('demo')\n")
    content_hash = hash_render_request(scene_path, {})

    preview = artifacts_dir / "scenes" / "_root" / "preview" / "demo_preview.mp4"
    final = artifacts_dir / "scenes" / "_root" / "final" / "demo_final.mp4"
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
                        "scene_path": "generated_old-uuid.py",
                        "scene_uuid": "old-uuid",
                        "preview": "_root/preview/demo_preview.mp4",
                        "final": "_root/final/demo_final.mp4",
                        "updated_at": "2026-05-04T00:00:00Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"old-uuid": content_hash},
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
            "/render",
            json={"scene_path": str(scene_path), "conversation_id": "conv-1"},
        )

    remapped_index = json.loads(index_path.read_text())
    assert response.status_code == 200
    assert remapped_index["by_scene_uuid"]["new-uuid"] == content_hash
    assert "old-uuid" not in remapped_index["by_scene_uuid"]


def test_render_queues_when_cached_final_is_missing(tmp_path, monkeypatch) -> None:
    """Queue a render when only partial cached artifacts exist."""
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    scene_path = scenes_dir / "demo_scene.py"
    scene_path.write_text("print('demo')\n")
    content_hash = hash_render_request(scene_path, {})

    preview = artifacts_dir / "scenes" / "_root" / "preview" / "demo_scene_preview.mp4"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"preview")

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
                        "final": None,
                        "updated_at": "2026-05-04T00:00:00Z",
                        "artifact_version": 1,
                    }
                },
                "by_scene_uuid": {"demo_scene": content_hash},
            }
        )
    )

    async def fake_create_queued_job(
        self, *, job_id: str, conversation_id: str
    ) -> RenderJobSnapshot:
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
            json={"scene_path": str(scene_path), "conversation_id": "conv-1"},
        )

    assert response.status_code == 200
    assert response.json()["job"]["status"] == "queued"
    kiq_mock.assert_awaited_once()
