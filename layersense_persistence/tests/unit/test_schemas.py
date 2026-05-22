import pytest
from layersense_persistence.repositories.frames import FramesRepository
from layersense_persistence.repositories.projects import ProjectsRepository
from layersense_persistence.repositories.renders import RendersRepository
from layersense_persistence.repositories.scenes import ScenesRepository
from layersense_persistence.schemas import ProjectRead, RenderRead, SceneWithFramesRead

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def test_dtos_validate_from_orm_models(session) -> None:
    """Convert ORM models into cross-service Pydantic DTOs."""
    project = ProjectsRepository(session).create(name="Demo")
    scene = ScenesRepository(session).create(project_id=project.id, name="Intro")
    frame = FramesRepository(session).create(scene_id=scene.id, excalidraw_frame_id="frame-1")
    render = RendersRepository(session).create(scene_id=scene.id, content_hash="hash")
    scene.frames = [frame]

    assert ProjectRead.model_validate(project).slug == "demo"
    assert SceneWithFramesRead.model_validate(scene).frames[0].excalidraw_frame_id == "frame-1"
    assert RenderRead.model_validate(render).status == "generating"
