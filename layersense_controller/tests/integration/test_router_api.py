import hashlib
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from layersense_controller.artifacts import hash_render_source
from layersense_controller.main import app
from layersense_controller.render_jobs import RenderJobSnapshot
from layersense_persistence.database import init_db
from layersense_storage.keys import render_preview_key, render_source_key

pytestmark = [pytest.mark.integration, pytest.mark.ai]

SOURCE_CODE = "from manim import Scene\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n"
SOURCE_HASH = hashlib.sha256(SOURCE_CODE.encode()).hexdigest()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("layersense_persistence.database.settings.db_path", tmp_path / "db.sqlite")
    monkeypatch.setattr("layersense_controller.config.settings.storage_root", tmp_path / "storage")
    monkeypatch.setattr("layersense_controller.config.settings.render_workdir", tmp_path / "work")
    init_db()
    with TestClient(app) as test_client:
        yield test_client, tmp_path


def test_render_writes_source_to_object_store_and_queues_task(client, monkeypatch) -> None:
    """Exercise the new raw-source /render contract through FastAPI."""
    test_client, tmp_path = client

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

    response = test_client.post(
        "/render",
        json={
            "source_code": SOURCE_CODE,
            "content_hash": SOURCE_HASH,
            "conversation_id": "conv-1",
        },
    )

    render_hash = hash_render_source(SOURCE_CODE, {})
    assert response.status_code == 200
    assert (tmp_path / "storage" / render_source_key(render_hash)).is_file()
    kiq_mock.assert_awaited_once()


def test_artifact_by_hash_serves_object_store_bytes(client) -> None:
    """Serve browser-facing artifacts from ObjectStore keys."""
    test_client, tmp_path = client
    content_hash = "hash-1"
    artifact_path = tmp_path / "storage" / render_preview_key(content_hash)
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"preview")

    response = test_client.get(f"/artifacts/by-hash/{content_hash}/preview")

    assert response.status_code == 200
    assert response.content == b"preview"


def test_render_rejects_legacy_scene_path_payload(client) -> None:
    """Keep the Step 3 HTTP-contract break loud."""
    test_client, _ = client

    response = test_client.post(
        "/render", json={"scene_path": "/tmp/scene.py", "conversation_id": "c"}
    )

    assert response.status_code == 422
