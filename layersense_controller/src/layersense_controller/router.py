import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from layersense_persistence.database import get_session
from layersense_persistence.repositories import RendersRepository, ScenesRepository
from layersense_storage.errors import ObjectNotFoundError
from layersense_storage.keys import render_final_key, render_preview_key, render_source_key
from pydantic import BaseModel, Field

from layersense_controller.artifacts import (
    canonical_cli_flags_json,
    create_queued_render,
    create_reused_render,
    ensure_default_scene,
    find_reusable_render,
    get_object_store,
    hash_render_source,
    hash_source_code,
)
from layersense_controller.broker import get_job_store
from layersense_controller.config import settings
from layersense_controller.render import CLIFlags
from layersense_controller.render_jobs import RenderJobSnapshot
from layersense_controller.render_runtime import artifact_url_by_hash

router = APIRouter()


class RenderRequest(BaseModel):
    source_code: str
    content_hash: str
    conversation_id: str
    cli_flags: CLIFlags = Field(default_factory=CLIFlags)


class RenderQueueResponse(BaseModel):
    job_id: str
    job: RenderJobSnapshot


def create_job_id() -> str:
    return uuid.uuid4().hex


async def enqueue_render_job(
    *,
    job_id: str,
    render_id: str,
    content_hash: str,
    cli_flags: CLIFlags,
) -> None:
    from layersense_controller.render_tasks import run_render_job

    await run_render_job.kiq(
        job_id=job_id,
        render_id=render_id,
        content_hash=content_hash,
        cli_flags=request_cli_flags_payload(cli_flags),
    )


def request_cli_flags_payload(cli_flags: CLIFlags) -> dict[str, object]:
    return cli_flags.model_dump(mode="json", exclude_none=True)


def _artifact_response(key: str) -> StreamingResponse:
    try:
        return StreamingResponse(get_object_store().open(key), media_type="video/mp4")
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/artifacts/by-hash/{content_hash}/{kind}")
async def get_artifact_by_hash(
    content_hash: str, kind: Literal["preview", "final"]
) -> StreamingResponse:
    key = render_preview_key(content_hash) if kind == "preview" else render_final_key(content_hash)
    return _artifact_response(key)


@router.get("/artifacts/scenes/{scene_uuid}")
async def get_artifact_for_scene(scene_uuid: str, preview: bool = False) -> StreamingResponse:
    with get_session() as session:
        scene = ScenesRepository(session).get(scene_uuid)
        if scene is None or scene.current_render_id is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        render = RendersRepository(session).get(scene.current_render_id)
        if render is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        key = (
            render.preview_artifact_key
            if preview
            else render.final_artifact_key or render.preview_artifact_key
        )
        if key is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
    return _artifact_response(key)


@router.get("/artifacts/{artifact_path:path}")
async def get_artifact(artifact_path: str) -> FileResponse:
    raise HTTPException(status_code=404, detail="Artifact not found")


@router.post("/render")
async def render(request: RenderRequest) -> RenderQueueResponse:
    cli_flags_payload = request_cli_flags_payload(request.cli_flags)
    if request.content_hash != hash_source_code(request.source_code):
        raise HTTPException(status_code=422, detail="content_hash does not match source_code")
    content_hash = hash_render_source(request.source_code, cli_flags_payload)
    cli_flags_json = canonical_cli_flags_json(cli_flags_payload)
    object_store = get_object_store()
    source_key = render_source_key(content_hash)
    job_id = create_job_id()

    with get_session() as session:
        scene = ensure_default_scene(session, request.conversation_id)
        cached_render = find_reusable_render(session, object_store, content_hash, cli_flags_json)
        if cached_render is not None:
            create_reused_render(
                session,
                scene_id=scene.id,
                source_render=cached_render,
                conversation_id=request.conversation_id,
            )
            job = await get_job_store().create_completed_job(
                job_id=job_id,
                conversation_id=request.conversation_id,
                preview_url=artifact_url_by_hash(content_hash, "preview"),
                final_url=artifact_url_by_hash(content_hash, "final"),
            )
            return RenderQueueResponse(job_id=job_id, job=job)

        object_store.put(source_key, request.source_code.encode(), content_type="text/x-python")
        render_row = create_queued_render(
            session,
            scene_id=scene.id,
            content_hash=content_hash,
            source_key=source_key,
            cli_flags_json=cli_flags_json,
            conversation_id=request.conversation_id,
        )

    job = await get_job_store().create_queued_job(
        job_id=job_id, conversation_id=request.conversation_id
    )
    await enqueue_render_job(
        job_id=job_id,
        render_id=render_row.id,
        content_hash=content_hash,
        cli_flags=request.cli_flags,
    )
    return RenderQueueResponse(job_id=job_id, job=job)


@router.get("/render-jobs/{job_id}")
async def get_render_job(
    job_id: str,
    after_version: int | None = Query(default=None),
    wait_seconds: int | None = Query(default=None),
) -> dict[str, object]:
    requested_wait = (
        wait_seconds
        if wait_seconds is not None and wait_seconds > 0
        else settings.render_job_wait_seconds
    )
    wait = min(requested_wait, settings.render_job_max_wait_seconds)
    job = await get_job_store().wait_for_newer_version(
        job_id,
        after_version=after_version,
        wait_seconds=wait,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Render job not found")
    return job.model_dump()
