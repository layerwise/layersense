import importlib

import pytest
from layersense_controller.artifacts import hash_render_source
from layersense_persistence.database import get_session, init_db
from layersense_persistence.repositories import (
    ProjectsRepository,
    RendersRepository,
    ScenesRepository,
)
from layersense_storage.keys import render_source_key
from layersense_storage.object_store import LocalFSObjectStore
from taskiq import InMemoryBroker

pytestmark = [pytest.mark.integration, pytest.mark.ai]

SOURCE_CODE = "print('demo')\n"


def _create_render(tmp_path, monkeypatch) -> tuple[str, str]:
    monkeypatch.setattr("layersense_persistence.database.settings.db_path", tmp_path / "db.sqlite")
    monkeypatch.setattr("layersense_controller.config.settings.storage_root", tmp_path / "storage")
    monkeypatch.setattr("layersense_controller.config.settings.render_workdir", tmp_path / "work")
    init_db()
    content_hash = hash_render_source(SOURCE_CODE, {"quality": "m", "renderer": "cairo"})
    source_key = render_source_key(content_hash)
    LocalFSObjectStore(tmp_path / "storage").put(source_key, SOURCE_CODE.encode())
    with get_session() as session:
        project = ProjectsRepository(session).create(name="_default", slug="_default")
        scene = ScenesRepository(session).create(project_id=project.id, name="scene")
        render = RendersRepository(session).create(
            scene_id=scene.id,
            content_hash=content_hash,
            status="queued",
            scene_py_artifact_key=source_key,
        )
    return render.id, content_hash


@pytest.mark.asyncio
async def test_run_render_job_kiq_executes_pipeline_and_deserializes_cli_flags(
    monkeypatch, tmp_path
) -> None:
    """Execute the render task through Taskiq and deserialize controller CLI flags."""
    broker = InMemoryBroker(await_inplace=True)
    import layersense_controller.broker as broker_module

    monkeypatch.setattr(broker_module, "broker", broker)
    render_tasks = importlib.reload(importlib.import_module("layersense_controller.render_tasks"))
    render_id, content_hash = _create_render(tmp_path, monkeypatch)
    preview_path = tmp_path / "preview.mp4"
    final_path = tmp_path / "final.mp4"
    transitions = []
    seen_cli_flags = []

    async def fake_render_preview(_scene_path, _content_hash, cli_flags=None):
        seen_cli_flags.append(cli_flags)
        preview_path.write_bytes(b"preview")
        return preview_path

    async def fake_render_final(_scene_path, _content_hash, cli_flags=None):
        seen_cli_flags.append(cli_flags)
        final_path.write_bytes(b"final")
        return final_path

    async def fake_update_job(self, job_id: str, status: str, **changes):
        transitions.append((status, changes))
        return None

    monkeypatch.setattr(render_tasks, "render_preview", fake_render_preview)
    monkeypatch.setattr(render_tasks, "render_final", fake_render_final)
    monkeypatch.setattr(
        render_tasks, "get_job_store", lambda: type("Store", (), {"update_job": fake_update_job})()
    )

    await broker.startup()
    try:
        task = await render_tasks.run_render_job.kiq(
            job_id="job-1",
            render_id=render_id,
            content_hash=content_hash,
            cli_flags={"quality": "m", "renderer": "cairo"},
        )
        await task.wait_result(timeout=2)
    finally:
        await broker.shutdown()

    assert seen_cli_flags[0].quality == "m"
    assert seen_cli_flags[0].renderer == "cairo"
    assert transitions[-1][0] == "succeeded"
