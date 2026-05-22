import pytest
from layersense_persistence.repositories.projects import ProjectsRepository
from layersense_persistence.repositories.renders import RendersRepository
from layersense_persistence.repositories.scenes import ScenesRepository

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def test_render_repository_tracks_status_artifacts_and_refinement(session) -> None:
    """Create render rows and update artifact status fields."""
    project = ProjectsRepository(session).create(name="Demo")
    scene = ScenesRepository(session).create(project_id=project.id, name="Intro")
    renders = RendersRepository(session)
    parent = renders.create(scene_id=scene.id, content_hash="hash-1", status="final_ready")
    child = renders.create(
        scene_id=scene.id,
        content_hash="hash-2",
        parent_render_id=parent.id,
        refinement_prompt="Make it smoother",
        conversation_id="conversation",
    )

    updated = renders.update_status(
        child.id,
        status="final_ready",
        scene_py_artifact_key="renders/hash-2/source.py",
        preview_artifact_key="renders/hash-2/preview.mp4",
        final_artifact_key="renders/hash-2/final.mp4",
        log_artifact_key="renders/hash-2/manim.log",
    )

    assert updated.parent_render_id == parent.id
    assert updated.refinement_prompt == "Make it smoother"
    assert updated.final_artifact_key == "renders/hash-2/final.mp4"
    assert [render.id for render in renders.list_by_content_hash("hash-2")] == [child.id]


def test_update_missing_render_raises_key_error(session) -> None:
    """Raise KeyError when updating a missing render."""
    with pytest.raises(KeyError):
        RendersRepository(session).update_status("missing", status="failed")
