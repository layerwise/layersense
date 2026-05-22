import pytest
from layersense_persistence.repositories.frames import FramesRepository
from layersense_persistence.repositories.projects import ProjectsRepository
from layersense_persistence.repositories.scenes import ScenesRepository

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def test_frame_repository_crud_and_ordering(session) -> None:
    """Create, list, update, reorder, and delete frames."""
    project = ProjectsRepository(session).create(name="Demo")
    scene = ScenesRepository(session).create(project_id=project.id, name="Intro")
    frames = FramesRepository(session)
    first = frames.create(scene_id=scene.id, excalidraw_frame_id="frame-1")
    second = frames.create(scene_id=scene.id, excalidraw_frame_id="frame-2")

    frames.update(first.id, prompt_augmentation="Zoom in")
    frames.reorder(scene.id, [second.id, first.id])

    assert frames.get(first.id).prompt_augmentation == "Zoom in"
    assert [frame.id for frame in frames.list_by_scene(scene.id)] == [second.id, first.id]

    frames.delete(second.id)
    assert frames.get(second.id) is None


def test_frame_reorder_rejects_partial_ids(session) -> None:
    """Reject frame reorder payloads that omit existing frames."""
    project = ProjectsRepository(session).create(name="Demo")
    scene = ScenesRepository(session).create(project_id=project.id, name="Intro")
    frame = FramesRepository(session).create(scene_id=scene.id, excalidraw_frame_id="frame-1")

    with pytest.raises(ValueError):
        FramesRepository(session).reorder(scene.id, [frame.id, "missing"])
