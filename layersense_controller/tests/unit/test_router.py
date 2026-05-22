import hashlib
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from layersense_controller.artifacts import hash_render_source
from layersense_controller.main import app
from layersense_controller.render_jobs import RenderJobSnapshot
from layersense_persistence.database import init_db
from layersense_persistence.repositories import (
    ProjectsRepository,
    RendersRepository,
    ScenesRepository,
)
from layersense_storage.keys import render_source_key

pytestmark = [pytest.mark.unit, pytest.mark.ai]


SOURCE_CODE = "from manim import Scene\n\nclass GeneratedScene(Scene):\n    def construct(self):\n        pass\n"
SOURCE_HASH = hashlib.sha256(SOURCE_CODE.encode()).hexdigest()


@pytest.fixture()
def configured_app(tmp_path, monkeypatch):
    db_path = tmp_path / "db.sqlite"
    monkeypatch.setattr("layersense_persistence.database.settings.db_path", db_path)
    monkeypatch.setattr("layersense_controller.config.settings.storage_root", tmp_path / "storage")
    monkeypatch.setattr("layersense_controller.config.settings.render_workdir", tmp_path / "work")
    init_db()
    with TestClient(app) as client:
        yield client, tmp_path


def test_render_rejects_legacy_scene_path_payload(configured_app) -> None:
    """Reject the removed scene_path-shaped render request contract."""
    client, _ = configured_app

    response = client.post("/render", json={"scene_path": "/tmp/scene.py", "conversation_id": "c"})

    assert response.status_code == 422


def test_render_stores_source_creates_default_scene_and_queues_task(
    configured_app, monkeypatch
) -> None:
    """Persist raw source into ObjectStore and enqueue a render row for the worker."""
    client, tmp_path = configured_app

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

    kiq_mock = AsyncMock(return_value=None)
    monkeypatch.setattr("layersense_controller.router.create_job_id", lambda: "job-1")
    monkeypatch.setattr(
        "layersense_controller.router.get_job_store",
        lambda: type("Store", (), {"create_queued_job": fake_create_queued_job})(),
    )
    monkeypatch.setattr("layersense_controller.render_tasks.run_render_job.kiq", kiq_mock)

    response = client.post(
        "/render",
        json={
            "source_code": SOURCE_CODE,
            "content_hash": SOURCE_HASH,
            "conversation_id": "conv-1",
            "cli_flags": {"quality": "m"},
        },
    )

    render_hash = hash_render_source(SOURCE_CODE, {"quality": "m"})
    assert response.status_code == 200
    assert response.json()["job"]["status"] == "queued"
    assert (tmp_path / "storage" / render_source_key(render_hash)).read_text() == SOURCE_CODE
    kiq_mock.assert_awaited_once()
    assert kiq_mock.await_args.kwargs["content_hash"] == render_hash
    with pytest.MonkeyPatch.context() as _:
        from layersense_persistence.database import get_session

        with get_session() as session:
            assert ProjectsRepository(session).get_by_slug("_default") is not None
            assert ScenesRepository(session).get("conv-1") is not None
            renders = RendersRepository(session).list_by_content_hash(render_hash)
            assert len(renders) == 1
            assert renders[0].scene_py_artifact_key == render_source_key(render_hash)


def test_render_rejects_source_hash_mismatch(configured_app) -> None:
    """Reject render requests where the forwarded agent source hash is stale."""
    client, _ = configured_app

    response = client.post(
        "/render",
        json={"source_code": SOURCE_CODE, "content_hash": "wrong", "conversation_id": "conv-1"},
    )

    assert response.status_code == 422
