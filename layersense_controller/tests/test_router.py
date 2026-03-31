import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from layersense_controller.config import settings
from layersense_controller.render import RenderError
from layersense_controller.router import _render_pipeline, router


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_health() -> None:
    client = _build_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_render_returns_404_for_missing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path / "artifacts")
    client = _build_client()
    missing_path = tmp_path / "missing_scene.py"

    response = client.post(
        "/render",
        json={"scene_path": str(missing_path), "conversation_id": "conv-1"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Scene file not found"


def test_render_returns_cached_when_artifacts_exist(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "demo_scene.py"
    scene_path.write_text("print('demo')\n")

    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    preview = artifacts_dir / f"{content_hash}_preview.mp4"
    final = artifacts_dir / f"{content_hash}_final.mp4"
    preview.write_bytes(b"preview")
    final.write_bytes(b"final")

    events: list[dict[str, str]] = []

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    client = _build_client()
    response = client.post(
        "/render",
        json={"scene_path": str(scene_path), "conversation_id": "conv-1"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "cached"}
    assert len(events) == 1
    assert events[0]["type"] == "artifact_ready"
    assert events[0]["preview_url"] == f"/artifacts/{preview.name}"
    assert events[0]["final_url"] == f"/artifacts/{final.name}"


def test_render_returns_404_for_directory_path(tmp_path) -> None:
    client = _build_client()
    directory_path = tmp_path / "scene_dir"
    directory_path.mkdir()

    response = client.post(
        "/render",
        json={"scene_path": str(directory_path), "conversation_id": "conv-1"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Scene file not found"


def test_render_returns_400_for_scene_outside_configured_scenes_dir(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "layersense_scenes"
    scenes_dir.mkdir()
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)
    client = _build_client()

    off_root_scene = tmp_path / "outside.py"
    off_root_scene.write_text("print('outside')\n")

    response = client.post(
        "/render",
        json={"scene_path": str(off_root_scene), "conversation_id": "conv-1"},
    )

    assert response.status_code == 400
    assert "configured scenes_dir" in response.json()["detail"]


def test_artifact_returns_404_for_directory(tmp_path, monkeypatch) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    (artifacts_dir / "dir.mp4").mkdir()

    client = _build_client()
    response = client.get("/artifacts/dir.mp4")

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact not found"


def test_render_queues_and_broadcasts_preview_and_final(tmp_path, monkeypatch, caplog) -> None:
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir = tmp_path / "layersense_scenes"
    artifacts_dir.mkdir()
    scenes_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)

    scene_path = scenes_dir / "queued_scene.py"
    scene_path.write_text("print('queued')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    preview_target = artifacts_dir / f"{content_hash}_preview.mp4"
    final_target = artifacts_dir / f"{content_hash}_final.mp4"

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        preview_target.write_bytes(b"preview")
        return preview_target

    async def fake_render_final(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        final_target.write_bytes(b"final")
        return final_target

    events: list[dict[str, str]] = []

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.render_final", fake_render_final)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    client = _build_client()
    with caplog.at_level("INFO", logger="layersense_controller.router"):
        response = client.post(
            "/render",
            json={"scene_path": str(scene_path), "conversation_id": "conv-queued"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "queued"}
    assert events == [
        {
            "type": "preview_ready",
            "conversation_id": "conv-queued",
            "url": f"/artifacts/{preview_target.name}",
        },
        {
            "type": "render_ready",
            "conversation_id": "conv-queued",
            "url": f"/artifacts/{final_target.name}",
        },
    ]
    assert preview_target.exists()
    assert final_target.exists()
    assert [record.message for record in caplog.records] == [
        f"render started for conv-queued: {scene_path}",
        f"preview ready for conv-queued: {preview_target}",
        f"render ready for conv-queued: {final_target}",
    ]


@pytest.mark.asyncio
async def test_render_pipeline_logs_and_broadcasts_render_error(
    tmp_path, monkeypatch, caplog
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    scene_path = tmp_path / "render_error_scene.py"
    scene_path.write_text("print('broken')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    render_error = RenderError("manim exited with code 1", "traceback lines")

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        raise render_error

    events: list[dict[str, str]] = []

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    with caplog.at_level("WARNING", logger="layersense_controller.router"):
        await _render_pipeline(
            scene_path=scene_path,
            content_hash=content_hash,
            conversation_id="conv-render-error",
        )

    assert events == [
        {
            "type": "render_failed",
            "conversation_id": "conv-render-error",
            "error": "manim exited with code 1",
            "stderr": "traceback lines",
        }
    ]
    assert [record.message for record in caplog.records if record.levelname == "WARNING"] == [
        (
            "render failed for conv-render-error at "
            f"{scene_path}: manim exited with code 1; stderr=traceback lines"
        )
    ]


@pytest.mark.asyncio
async def test_render_pipeline_broadcasts_failure_for_unexpected_errors(
    tmp_path, monkeypatch
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

    scene_path = tmp_path / "broken_scene.py"
    scene_path.write_text("print('broken')\n")
    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()

    async def fake_render_preview(scene_path_arg, content_hash_arg):
        assert scene_path_arg == scene_path
        assert content_hash_arg == content_hash
        raise RuntimeError("preview exploded")

    events: list[dict[str, str]] = []

    async def fake_broadcast(event: dict[str, str]) -> None:
        events.append(event)

    monkeypatch.setattr("layersense_controller.router.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.router.manager.broadcast", fake_broadcast)

    await _render_pipeline(
        scene_path=scene_path,
        content_hash=content_hash,
        conversation_id="conv-fail",
    )

    assert events == [
        {
            "type": "render_failed",
            "conversation_id": "conv-fail",
            "error": "preview exploded",
            "stderr": "",
        }
    ]
