import pytest
from layersense_persistence.config import PersistenceSettings
from layersense_persistence.database import _sqlite_url, create_engine, get_session, init_db
from layersense_persistence.repositories.frames import FramesRepository
from layersense_persistence.repositories.projects import ProjectsRepository
from layersense_persistence.repositories.renders import RendersRepository
from layersense_persistence.repositories.scenes import ScenesRepository
from sqlalchemy import create_engine as sqlalchemy_create_engine

pytestmark = [pytest.mark.integration, pytest.mark.ai]


def test_repositories_round_trip_against_file_sqlite(tmp_path) -> None:
    """Exercise all repositories against a file-backed SQLite database."""
    engine = create_engine(PersistenceSettings(db_path=tmp_path / "repo.sqlite"))
    init_db(engine)

    with get_session(engine) as session:
        projects = ProjectsRepository(session)
        scenes = ScenesRepository(session)
        frames = FramesRepository(session)
        renders = RendersRepository(session)

        project = projects.create(name="Über Demo")
        duplicate_slug_project = projects.create(name="Uber Demo")
        projects.update(
            project.id, name="Renamed Demo", default_render_config_json='{"quality":"l"}'
        )

        first_scene = scenes.create(project_id=project.id, name="Intro")
        second_scene = scenes.create(project_id=project.id, name="Outro")
        scenes.update(
            first_scene.id,
            prompt="Explain eigenvectors",
            excalidraw_scene_json='{"elements":[]}',
            thumbnail_artifact_key="renders/hash/thumbnail.png",
        )
        scenes.reorder(project.id, [second_scene.id, first_scene.id])

        first_frame = frames.create(scene_id=first_scene.id, excalidraw_frame_id="frame-1")
        second_frame = frames.create(scene_id=first_scene.id, excalidraw_frame_id="frame-2")
        frames.update(first_frame.id, prompt_augmentation="Zoom in")
        frames.reorder(first_scene.id, [second_frame.id, first_frame.id])

        parent_render = renders.create(
            scene_id=first_scene.id,
            content_hash="hash-parent",
            status="final_ready",
            final_artifact_key="renders/hash-parent/final.mp4",
        )
        child_render = renders.create(
            scene_id=first_scene.id,
            content_hash="hash-child",
            parent_render_id=parent_render.id,
            refinement_prompt="Smoother transition",
            conversation_id="conversation",
        )
        renders.update_status(
            child_render.id,
            status="failed",
            scene_py_artifact_key="renders/hash-child/source.py",
            preview_artifact_key="renders/hash-child/preview.mp4",
            error_message="boom",
        )
        scenes.set_current_render(first_scene.id, child_render.id)

        assert project.slug == "uber-demo"
        assert duplicate_slug_project.slug == "uber-demo-2"
        assert projects.get_by_slug("uber-demo") is not None
        assert [project.id for project in projects.list()] == [
            project.id,
            duplicate_slug_project.id,
        ]
        assert [scene.id for scene in scenes.list_by_project(project.id)] == [
            second_scene.id,
            first_scene.id,
        ]
        assert [frame.id for frame in frames.list_by_scene(first_scene.id)] == [
            second_frame.id,
            first_frame.id,
        ]
        assert renders.list_by_scene(first_scene.id)[0].id == child_render.id
        assert renders.list_by_content_hash("hash-child")[0].error_message == "boom"


def test_repository_deletes_remove_rows_against_file_sqlite(tmp_path) -> None:
    """Delete render, frame, scene, and project rows through repository methods."""
    engine = create_engine(PersistenceSettings(db_path=tmp_path / "delete.sqlite"))
    init_db(engine)

    with get_session(engine) as session:
        projects = ProjectsRepository(session)
        scenes = ScenesRepository(session)
        frames = FramesRepository(session)
        renders = RendersRepository(session)
        project = projects.create(name="Delete Me")
        scene = scenes.create(project_id=project.id, name="Scene")
        frame = frames.create(scene_id=scene.id, excalidraw_frame_id="frame")
        render = renders.create(scene_id=scene.id, content_hash="hash")

        renders.delete(render.id)
        frames.delete(frame.id)
        scenes.delete(scene.id)
        projects.delete(project.id)

        assert renders.get(render.id) is None
        assert frames.get(frame.id) is None
        assert scenes.get(scene.id) is None
        assert projects.get(project.id) is None


def test_repository_validation_paths_against_file_sqlite(tmp_path) -> None:
    """Exercise repository missing-row and invalid-reorder branches."""
    engine = create_engine(PersistenceSettings(db_path=tmp_path / "errors.sqlite"))
    init_db(engine)

    with get_session(engine) as session:
        project = ProjectsRepository(session).create(name="Errors")
        scene = ScenesRepository(session).create(project_id=project.id, name="Scene")
        frame = FramesRepository(session).create(scene_id=scene.id, excalidraw_frame_id="frame")

        with pytest.raises(KeyError):
            ProjectsRepository(session).update("missing", name="Nope")
        with pytest.raises(KeyError):
            ScenesRepository(session).set_current_render("missing", None)
        with pytest.raises(KeyError):
            FramesRepository(session).update("missing", prompt_augmentation="Nope")
        with pytest.raises(KeyError):
            RendersRepository(session).delete("missing")
        with pytest.raises(ValueError):
            ScenesRepository(session).reorder(project.id, [scene.id, "missing"])
        with pytest.raises(ValueError):
            FramesRepository(session).reorder(scene.id, [frame.id, "missing"])


def test_database_helpers_support_defaults_and_rollbacks(tmp_path, monkeypatch) -> None:
    """Exercise default engine/session helpers and rollback behavior."""
    db_path = tmp_path / "default.sqlite"
    monkeypatch.setattr("layersense_persistence.config.settings.db_path", db_path)
    monkeypatch.setattr("layersense_persistence.database.settings.db_path", db_path)

    init_db()
    with pytest.raises(RuntimeError):
        with get_session() as session:
            ProjectsRepository(session).create(name="Rolled Back")
            raise RuntimeError("rollback")

    verification_engine = sqlalchemy_create_engine(f"sqlite+pysqlite:///{db_path}")
    with get_session(verification_engine) as session:
        assert ProjectsRepository(session).list() == []
        ProjectsRepository(session).create(name="Committed")

    assert _sqlite_url(":memory:") == "sqlite+pysqlite:///:memory:"
