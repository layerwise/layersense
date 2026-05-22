from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from layersense_persistence.repositories import (
    ProjectsRepository,
    RendersRepository,
    ScenesRepository,
)
from layersense_storage.keys import (
    render_final_key,
    render_log_key,
    render_preview_key,
)
from layersense_storage.object_store import LocalFSObjectStore, ObjectStore
from sqlalchemy.orm import Session

from layersense_controller.config import settings


def canonical_cli_flags_json(cli_flags: dict[str, object]) -> str:
    return json.dumps(cli_flags, sort_keys=True, separators=(",", ":"))


def hash_render_source(source_code: str, cli_flags: dict[str, object]) -> str:
    payload = source_code.encode() + canonical_cli_flags_json(cli_flags).encode()
    return hashlib.sha256(payload).hexdigest()


def hash_source_code(source_code: str) -> str:
    return hashlib.sha256(source_code.encode()).hexdigest()


def get_object_store() -> ObjectStore:
    return LocalFSObjectStore(settings.storage_root)


def ensure_default_scene(session: Session, conversation_id: str):
    projects = ProjectsRepository(session)
    scenes = ScenesRepository(session)
    project = projects.get_by_slug("_default")
    if project is None:
        project = projects.create(name="_default", slug="_default")

    scene = scenes.get(conversation_id)
    if scene is not None:
        return scene

    # TODO(step-4): remove. See docs/plans/2026-05-21-frontend-revamp-and-project-scene-crud-plan.md §"_default shim wipe".
    scene = scenes.create(project_id=project.id, name=conversation_id)
    scene.id = conversation_id
    session.flush()
    return scene


def find_reusable_render(
    session: Session, object_store: ObjectStore, content_hash: str, cli_flags_json: str
):
    for render in RendersRepository(session).list_by_content_hash(content_hash):
        if render.cli_flags_json != cli_flags_json:
            continue
        if not render.preview_artifact_key or not render.final_artifact_key:
            continue
        if object_store.head(render.preview_artifact_key) and object_store.head(
            render.final_artifact_key
        ):
            return render
    return None


def create_queued_render(
    session: Session,
    *,
    scene_id: str,
    content_hash: str,
    source_key: str,
    cli_flags_json: str,
    conversation_id: str,
):
    render = RendersRepository(session).create(
        scene_id=scene_id,
        content_hash=content_hash,
        status="queued",
        scene_py_artifact_key=source_key,
        cli_flags_json=cli_flags_json,
        conversation_id=conversation_id,
    )
    ScenesRepository(session).set_current_render(scene_id, render.id)
    return render


def create_reused_render(
    session: Session,
    *,
    scene_id: str,
    source_render,
    conversation_id: str,
):
    render = RendersRepository(session).create(
        scene_id=scene_id,
        content_hash=source_render.content_hash,
        status="final_ready",
        scene_py_artifact_key=source_render.scene_py_artifact_key,
        preview_artifact_key=source_render.preview_artifact_key,
        final_artifact_key=source_render.final_artifact_key,
        log_artifact_key=source_render.log_artifact_key,
        cli_flags_json=source_render.cli_flags_json,
        conversation_id=conversation_id,
    )
    ScenesRepository(session).set_current_render(scene_id, render.id)
    return render


@contextmanager
def materialize_scene_source_for_manim(
    object_store: ObjectStore, *, source_key: str, render_id: str
) -> Iterator[Path]:
    settings.render_workdir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f"{render_id}-", dir=settings.render_workdir) as workdir:
        source_file_path = Path(workdir) / "scene.py"
        source_file_path.write_bytes(object_store.get(source_key))
        yield source_file_path


def store_render_outputs(
    session: Session,
    object_store: ObjectStore,
    *,
    render_id: str,
    content_hash: str,
    preview_path: Path | None = None,
    final_path: Path | None = None,
    log_text: str | None = None,
):
    preview_key = None
    final_key = None
    log_key = None
    if preview_path is not None:
        preview_key = render_preview_key(content_hash)
        with preview_path.open("rb") as source:
            object_store.put_stream(preview_key, source, content_type="video/mp4")
    if final_path is not None:
        final_key = render_final_key(content_hash)
        with final_path.open("rb") as source:
            object_store.put_stream(final_key, source, content_type="video/mp4")
    if log_text is not None:
        log_key = render_log_key(content_hash)
        object_store.put(log_key, log_text.encode(), content_type="text/plain")

    status = "final_ready" if final_key else "preview_ready"
    render = RendersRepository(session).update_status(
        render_id,
        status=status,
        preview_artifact_key=preview_key,
        final_artifact_key=final_key,
        log_artifact_key=log_key,
    )
    if preview_key is not None:
        ScenesRepository(session).update(render.scene_id, thumbnail_artifact_key=preview_key)
    return render


def clear_render_workdir() -> None:
    settings.render_workdir.mkdir(parents=True, exist_ok=True)
    for path in settings.render_workdir.iterdir():
        if path.is_dir():
            shutil.rmtree(path)
