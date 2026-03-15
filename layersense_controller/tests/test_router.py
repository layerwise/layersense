import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient
from layersense_controller.config import settings
from layersense_controller.router import router


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
    monkeypatch.setattr(settings, "scenes_dir", tmp_path / "scenes")
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path / "artifacts")
    client = _build_client()

    response = client.post(
        "/render",
        json={"scene_path": "missing_scene.py", "conversation_id": "conv-1"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Scene file not found"


def test_render_returns_cached_when_artifacts_exist(tmp_path, monkeypatch) -> None:
    scenes_dir = tmp_path / "scenes"
    artifacts_dir = tmp_path / "artifacts"
    scenes_dir.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setattr(settings, "scenes_dir", scenes_dir)
    monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)

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
        json={"scene_path": "demo_scene.py", "conversation_id": "conv-1"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "cached"}
    assert len(events) == 1
    assert events[0]["type"] == "artifact_ready"
    assert events[0]["preview_url"] == f"/artifacts/{preview.name}"
    assert events[0]["final_url"] == f"/artifacts/{final.name}"
