import pytest
from layersense_persistence.models import Frame, Project, Scene
from layersense_persistence.repositories.frames import FramesRepository
from layersense_persistence.repositories.projects import ProjectsRepository
from layersense_persistence.repositories.scenes import ScenesRepository
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

pytestmark = [pytest.mark.unit, pytest.mark.ai]


def test_sqlite_foreign_keys_are_enforced(session) -> None:
    """Reject child rows that point at missing parents."""
    session.add(Scene(id="scene", project_id="missing", name="Scene", order_index=0))

    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_scene_constraints_include_order_and_name_uniqueness(session) -> None:
    """Preserve canonical per-project scene uniqueness constraints."""
    project = ProjectsRepository(session).create(name="Demo")
    ScenesRepository(session).create(project_id=project.id, name="Intro", order_index=0)
    session.add(Scene(id="dupe", project_id=project.id, name="Intro", order_index=1))

    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_project_delete_cascades_scenes_and_frames(session) -> None:
    """Cascade project deletion through scenes and frames."""
    projects = ProjectsRepository(session)
    project = projects.create(name="Demo")
    scene = ScenesRepository(session).create(project_id=project.id, name="Intro")
    frame = FramesRepository(session).create(scene_id=scene.id, excalidraw_frame_id="frame-1")

    projects.delete(project.id)

    assert session.get(Project, project.id) is None
    assert session.get(Scene, scene.id) is None
    assert session.get(Frame, frame.id) is None


def test_wal_mode_is_enabled(sqlite_engine) -> None:
    """Enable WAL for file-backed SQLite engines."""
    with sqlite_engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
