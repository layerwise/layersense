import hashlib

import pytest
from layersense_controller.config import settings
from layersense_controller.render import RenderError
from layersense_controller.render_tasks import _run_render_pipeline

pytestmark = [pytest.mark.unit, pytest.mark.ai]


@pytest.mark.asyncio
async def test_run_render_pipeline_updates_preview_then_final(monkeypatch, tmp_path) -> None:
    """Advance render jobs through preview and final success states."""
    scene_path = tmp_path / "layersense_scenes" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('demo')\n")
    monkeypatch.setattr(settings, "scenes_dir", tmp_path / "layersense_scenes")
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path / "artifacts")
    preview_path = tmp_path / "artifacts" / "scenes" / "_root" / "preview" / "scene_preview.mp4"
    final_path = tmp_path / "artifacts" / "scenes" / "_root" / "final" / "scene_final.mp4"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    transitions: list[tuple[str, dict[str, str | None]]] = []

    async def fake_render_preview(_scene_path, _content_hash, _render_options=None):
        preview_path.write_bytes(b"preview")
        return preview_path

    async def fake_render_final(_scene_path, _content_hash, _render_options=None):
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
    """Mark render jobs failed when rendering raises a render error."""
    scene_path = tmp_path / "layersense_scenes" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('demo')\n")
    monkeypatch.setattr(settings, "scenes_dir", tmp_path / "layersense_scenes")
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path / "artifacts")

    transitions: list[tuple[str, dict[str, str | None]]] = []

    async def fake_render_preview(_scene_path, _content_hash, _render_options=None):
        raise RenderError("manim exited with code 1", "stderr text")

    async def fake_update_job(self, job_id: str, status: str, **changes: str | None):
        transitions.append((status, changes))
        return None

    monkeypatch.setattr("layersense_controller.render_tasks.render_preview", fake_render_preview)
    monkeypatch.setattr(
        "layersense_controller.render_tasks.get_job_store",
        lambda: type("Store", (), {"update_job": fake_update_job})(),
    )

    await _run_render_pipeline(
        job_id="job-1",
        scene_path=scene_path,
        content_hash="hash-1",
        conversation_id="conv-1",
    )

    assert transitions[-1] == (
        "failed",
        {"error": "manim exited with code 1", "stderr": "stderr text"},
    )


@pytest.mark.asyncio
async def test_run_render_pipeline_preserves_preview_before_final_completion(
    monkeypatch, tmp_path
) -> None:
    """Keep preview URLs published while final rendering is still pending."""
    scene_path = tmp_path / "layersense_scenes" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('demo')\n")
    monkeypatch.setattr(settings, "scenes_dir", tmp_path / "layersense_scenes")
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path / "artifacts")
    preview_path = tmp_path / "artifacts" / "scenes" / "_root" / "preview" / "scene_preview.mp4"
    final_path = tmp_path / "artifacts" / "scenes" / "_root" / "final" / "scene_final.mp4"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    transitions: list[tuple[str, dict[str, str | None]]] = []

    async def fake_render_preview(_scene_path, _content_hash, _render_options=None):
        preview_path.write_bytes(b"preview")
        return preview_path

    async def fake_render_final(_scene_path, _content_hash, _render_options=None):
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

    assert transitions[1] == (
        "waiting_for_final",
        {"preview_url": "/artifacts/by-hash/hash-1/preview"},
    )
    assert transitions[2] == ("final_rendering", {})


@pytest.mark.asyncio
async def test_run_render_pipeline_preserves_preview_url_when_final_fails(
    monkeypatch, tmp_path
) -> None:
    """Preserve preview URLs when final rendering fails after preview success."""
    scene_path = tmp_path / "layersense_scenes" / "scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('demo')\n")
    monkeypatch.setattr(settings, "scenes_dir", tmp_path / "layersense_scenes")
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path / "artifacts")
    preview_path = tmp_path / "artifacts" / "scenes" / "_root" / "preview" / "scene_preview.mp4"
    preview_path.parent.mkdir(parents=True, exist_ok=True)

    transitions: list[tuple[str, dict[str, str | None]]] = []

    async def fake_render_preview(_scene_path, _content_hash, _render_options=None):
        preview_path.write_bytes(b"preview")
        return preview_path

    async def fake_render_final(_scene_path, _content_hash, _render_options=None):
        raise RenderError("manim exited with code 2", "final stderr")

    async def fake_update_job(self, job_id: str, status: str, **changes: str | None):
        transitions.append((status, changes))
        return None

    monkeypatch.setattr("layersense_controller.render_tasks.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.render_tasks.render_final", fake_render_final)
    monkeypatch.setattr(
        "layersense_controller.render_tasks.get_job_store",
        lambda: type("Store", (), {"update_job": fake_update_job})(),
    )
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

    assert transitions[-1] == (
        "failed",
        {
            "preview_url": "/artifacts/by-hash/hash-1/preview",
            "error": "manim exited with code 2",
            "stderr": "final stderr",
        },
    )


@pytest.mark.asyncio
async def test_run_render_pipeline_renders_non_generated_scene_when_hash_match_belongs_to_other_scene(
    monkeypatch, tmp_path
) -> None:
    """Cache manual scene artifacts even when their hash was seen elsewhere."""
    scene_path = tmp_path / "layersense_scenes" / "algebra" / "demo_scene.py"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text("print('demo')\n")
    monkeypatch.setattr(settings, "scenes_dir", tmp_path / "layersense_scenes")
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path / "artifacts")
    preview_path = (
        tmp_path / "artifacts" / "scenes" / "algebra" / "preview" / "demo_scene_preview.mp4"
    )
    final_path = tmp_path / "artifacts" / "scenes" / "algebra" / "final" / "demo_scene_final.mp4"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    store_calls: list[dict[str, str | None]] = []

    async def fake_render_preview(_scene_path, _content_hash, _render_options=None):
        preview_path.write_bytes(b"preview")
        return preview_path

    async def fake_render_final(_scene_path, _content_hash, _render_options=None):
        final_path.write_bytes(b"final")
        return final_path

    async def fake_update_job(self, job_id: str, status: str, **changes: str | None):
        return None

    def fake_store_cached_artifacts(**kwargs: str | None) -> None:
        store_calls.append(kwargs)

    monkeypatch.setattr("layersense_controller.render_tasks.render_preview", fake_render_preview)
    monkeypatch.setattr("layersense_controller.render_tasks.render_final", fake_render_final)
    monkeypatch.setattr(
        "layersense_controller.render_tasks.get_job_store",
        lambda: type("Store", (), {"update_job": fake_update_job})(),
    )
    monkeypatch.setattr(
        "layersense_controller.render_tasks.store_cached_artifacts",
        fake_store_cached_artifacts,
    )

    content_hash = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    await _run_render_pipeline(
        job_id="job-1",
        scene_path=scene_path,
        content_hash=content_hash,
        conversation_id="conv-1",
    )

    assert store_calls == [
        {
            "content_hash": content_hash,
            "scene_uuid": "demo_scene",
            "scene_path": "algebra/demo_scene.py",
            "preview": "algebra/preview/demo_scene_preview.mp4",
        },
        {
            "content_hash": content_hash,
            "scene_uuid": "demo_scene",
            "scene_path": "algebra/demo_scene.py",
            "final": "algebra/final/demo_scene_final.mp4",
        },
    ]
