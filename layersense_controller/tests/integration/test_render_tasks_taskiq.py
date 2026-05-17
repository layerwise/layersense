import importlib

import pytest
from layersense_controller.config import settings
from taskiq import InMemoryBroker

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


@pytest.mark.asyncio
async def test_run_render_job_kiq_preserves_preview_url_when_final_raises_unexpected_error(
    monkeypatch, tmp_path
) -> None:
    """Keep preview_url on failed jobs when the final phase raises after preview succeeded."""
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
    preview_path.parent.mkdir(parents=True, exist_ok=True)

    transitions = []

    async def fake_render_preview(_scene_path, _content_hash, render_options=None):
        preview_path.write_bytes(b"preview")
        return preview_path

    async def fake_render_final(_scene_path, _content_hash, render_options=None):
        raise RuntimeError("boom")

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

    assert transitions[-1] == (
        "failed",
        {
            "preview_url": "/artifacts/by-hash/hash-1/preview",
            "error": "boom",
            "stderr": "",
        },
    )


@pytest.mark.asyncio
async def test_run_render_job_kiq_accepts_missing_render_options(monkeypatch, tmp_path) -> None:
    """Allow Taskiq-dispatched render jobs with no render_options payload."""
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
            render_options=None,
        )
        await task.wait_result(timeout=2)
    finally:
        await broker.shutdown()

    assert seen_render_options == [None, None]
