import pytest
from layersense_controller.artifacts import hash_render_source
from layersense_controller.render import RenderError
from layersense_controller.render_tasks import _run_render_pipeline
from layersense_persistence.database import get_session, init_db
from layersense_persistence.repositories import (
    ProjectsRepository,
    RendersRepository,
    ScenesRepository,
)
from layersense_storage.keys import render_source_key
from layersense_storage.object_store import LocalFSObjectStore

pytestmark = [pytest.mark.unit, pytest.mark.ai]

SOURCE_CODE = "print('demo')\n"


def _create_render(tmp_path, monkeypatch) -> tuple[str, str]:
    monkeypatch.setattr("layersense_persistence.database.settings.db_path", tmp_path / "db.sqlite")
    monkeypatch.setattr("layersense_controller.config.settings.storage_root", tmp_path / "storage")
    monkeypatch.setattr("layersense_controller.config.settings.render_workdir", tmp_path / "work")
    init_db()
    content_hash = hash_render_source(SOURCE_CODE, {})
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
async def test_run_render_pipeline_updates_preview_then_final(monkeypatch, tmp_path) -> None:
    """Advance render jobs through preview and final success states and store blobs."""
    render_id, content_hash = _create_render(tmp_path, monkeypatch)
    preview_path = tmp_path / "preview.mp4"
    final_path = tmp_path / "final.mp4"
    transitions: list[tuple[str, dict[str, str | None]]] = []

    async def fake_render_preview(_scene_path, _content_hash, _cli_flags=None):
        preview_path.write_bytes(b"preview")
        return preview_path

    async def fake_render_final(_scene_path, _content_hash, _cli_flags=None):
        final_path.write_bytes(b"final")
        return final_path

    async def fake_update_job(self, job_id: str, status: str, **changes: str | None):
        transitions.append((status, changes))
        return None

    monkeypatch.setattr("layersense_controller.render_tasks.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.render_tasks.render_final", fake_render_final)
    monkeypatch.setattr(
        "layersense_controller.render_tasks.get_job_store",
        lambda: type("Store", (), {"update_job": fake_update_job})(),
    )

    await _run_render_pipeline(job_id="job-1", render_id=render_id, content_hash=content_hash)

    assert transitions == [
        ("preview_rendering", {}),
        ("waiting_for_final", {"preview_url": f"/artifacts/by-hash/{content_hash}/preview"}),
        ("final_rendering", {}),
        (
            "succeeded",
            {
                "preview_url": f"/artifacts/by-hash/{content_hash}/preview",
                "final_url": f"/artifacts/by-hash/{content_hash}/final",
            },
        ),
    ]
    with get_session() as session:
        render = RendersRepository(session).get(render_id)
        assert render is not None
        assert render.status == "final_ready"
        assert render.preview_artifact_key is not None
        assert render.final_artifact_key is not None


@pytest.mark.asyncio
async def test_run_render_pipeline_marks_failed_on_render_error(monkeypatch, tmp_path) -> None:
    """Mark render jobs failed when rendering raises a render error."""
    render_id, content_hash = _create_render(tmp_path, monkeypatch)
    transitions: list[tuple[str, dict[str, str | None]]] = []

    async def fake_render_preview(_scene_path, _content_hash, _cli_flags=None):
        raise RenderError("manim exited with code 1", "stderr text")

    async def fake_update_job(self, job_id: str, status: str, **changes: str | None):
        transitions.append((status, changes))
        return None

    monkeypatch.setattr("layersense_controller.render_tasks.render_preview", fake_render_preview)
    monkeypatch.setattr(
        "layersense_controller.render_tasks.get_job_store",
        lambda: type("Store", (), {"update_job": fake_update_job})(),
    )

    await _run_render_pipeline(job_id="job-1", render_id=render_id, content_hash=content_hash)

    assert transitions[-1] == (
        "failed",
        {"error": "manim exited with code 1", "stderr": "stderr text"},
    )
    with get_session() as session:
        render = RendersRepository(session).get(render_id)
        assert render is not None
        assert render.status == "failed"
