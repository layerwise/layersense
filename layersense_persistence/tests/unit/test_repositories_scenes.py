import pytest
from layersense_persistence.repositories.projects import ProjectsRepository
from layersense_persistence.repositories.renders import RendersRepository
from layersense_persistence.repositories.scenes import ScenesRepository

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def test_scene_repository_crud_and_ordering(session) -> None:
    """Create, list, update, and delete scenes by project."""
    project = ProjectsRepository(session).create(name="Demo")
    scenes = ScenesRepository(session)
    first = scenes.create(project_id=project.id, name="First", order_index=0)
    second = scenes.create(project_id=project.id, name="Second")

    listed = scenes.list_by_project(project.id)
    assert [scene.name for scene in listed] == ["First", "Second"]

    scenes.update(first.id, prompt="Prompt", excalidraw_scene_json='{"elements":[]}')
    assert scenes.get(first.id).prompt == "Prompt"

    scenes.delete(second.id)
    assert scenes.get(second.id) is None


def test_scene_reorder_uses_collision_safe_two_phase_update(session) -> None:
    """Reorder scenes without tripping unique order constraints."""
    project = ProjectsRepository(session).create(name="Demo")
    scenes = ScenesRepository(session)
    first = scenes.create(project_id=project.id, name="First")
    second = scenes.create(project_id=project.id, name="Second")
    third = scenes.create(project_id=project.id, name="Third")

    scenes.reorder(project.id, [third.id, first.id, second.id])

    assert [scene.id for scene in scenes.list_by_project(project.id)] == [
        third.id,
        first.id,
        second.id,
    ]


def test_scene_current_render_points_at_render_row(session) -> None:
    """Set the denormalized current render id on a scene."""
    project = ProjectsRepository(session).create(name="Demo")
    scene = ScenesRepository(session).create(project_id=project.id, name="Intro")
    render = RendersRepository(session).create(scene_id=scene.id, content_hash="hash")

    updated = ScenesRepository(session).set_current_render(scene.id, render.id)

    assert updated.current_render_id == render.id


def test_scene_reorder_rejects_missing_ids(session) -> None:
    """Reject partial reorder payloads."""
    project = ProjectsRepository(session).create(name="Demo")
    scene = ScenesRepository(session).create(project_id=project.id, name="Intro")

    with pytest.raises(ValueError):
        ScenesRepository(session).reorder(project.id, [scene.id, "missing"])
