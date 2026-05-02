import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from layersense_domain.models import RenderOptions
from pydantic import BaseModel, Field

from layersense_controller.broker import get_job_store
from layersense_controller.cache import (
    hash_render_request,
    lookup_cached_artifacts,
    lookup_content_hash_for_scene,
    store_cached_artifacts,
)
from layersense_controller.config import settings
from layersense_controller.render import RenderError, _scene_path_relative_to_scenes_dir
from layersense_controller.render_jobs import RenderJobSnapshot
from layersense_controller.render_runtime import (
    artifact_url_by_hash,
    is_generated_scene_path,
    scene_uuid_from_scene_path,
)

router = APIRouter()


class RenderRequest(BaseModel):
    scene_path: str
    conversation_id: str
    render_options: RenderOptions = Field(default_factory=RenderOptions)


class RenderQueueResponse(BaseModel):
    job_id: str
    job: RenderJobSnapshot


def create_job_id() -> str:
    return uuid.uuid4().hex


async def enqueue_render_job(
    *,
    job_id: str,
    scene_path: str,
    content_hash: str,
    conversation_id: str,
    render_options: RenderOptions,
) -> None:
    from layersense_controller.render_tasks import run_render_job

    await run_render_job.kiq(
        job_id=job_id,
        scene_path=scene_path,
        content_hash=content_hash,
        conversation_id=conversation_id,
        render_options=request_render_options_payload(render_options),
    )


def request_render_options_payload(render_options: RenderOptions) -> dict[str, str | None]:
    return render_options.model_dump(mode="json", exclude_none=False)


def _scene_artifact_path(relative_path: str) -> Path:
    candidate = (settings.artifacts_dir / "scenes" / relative_path).resolve()
    artifacts_root = (settings.artifacts_dir / "scenes").resolve()

    try:
        candidate.relative_to(artifacts_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc

    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return candidate


def _artifact_response_from_scene_relative(relative_path: str) -> FileResponse:
    candidate = _scene_artifact_path(relative_path)
    return FileResponse(path=candidate, media_type="video/mp4", filename=candidate.name)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/artifacts/by-hash/{content_hash}/{kind}")
async def get_artifact_by_hash(
    content_hash: str, kind: Literal["preview", "final"]
) -> FileResponse:
    cached = lookup_cached_artifacts(content_hash)
    if cached is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    relative_path = cached[kind]
    if relative_path is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return _artifact_response_from_scene_relative(relative_path)


@router.get("/artifacts/scenes/{scene_uuid}")
async def get_artifact_for_scene(scene_uuid: str, preview: bool = False) -> FileResponse:
    content_hash = lookup_content_hash_for_scene(scene_uuid)
    if content_hash is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    cached = lookup_cached_artifacts(content_hash)
    if cached is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    relative_path = cached["preview"] if preview else cached["final"] or cached["preview"]
    if relative_path is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return _artifact_response_from_scene_relative(relative_path)


@router.get("/artifacts/{artifact_path:path}")
async def get_artifact(artifact_path: str) -> FileResponse:
    candidate = (settings.artifacts_dir / artifact_path).resolve()
    artifacts_root = (settings.artifacts_dir / "scenes").resolve()

    try:
        candidate.relative_to(artifacts_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc

    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path=candidate, media_type="video/mp4", filename=candidate.name)


@router.post("/render")
async def render(request: RenderRequest) -> RenderQueueResponse:
    scene_path = Path(request.scene_path)
    if not scene_path.exists() or not scene_path.is_file():
        raise HTTPException(status_code=404, detail="Scene file not found")

    try:
        scene_relative_path = _scene_path_relative_to_scenes_dir(scene_path)
    except RenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    render_options_payload = request_render_options_payload(request.render_options)
    content_hash = hash_render_request(scene_path, render_options_payload)
    cached = lookup_cached_artifacts(content_hash)
    scene_uuid = scene_uuid_from_scene_path(scene_path)
    job_id = create_job_id()

    if (
        cached
        and cached["preview"]
        and cached["final"]
        and (cached["scene_uuid"] == scene_uuid or is_generated_scene_path(scene_path))
    ):
        if cached["scene_uuid"] != scene_uuid:
            store_cached_artifacts(
                content_hash=content_hash,
                scene_uuid=scene_uuid,
                scene_path=scene_relative_path.as_posix(),
                preview=cached["preview"],
                final=cached["final"],
            )
        job = await get_job_store().create_completed_job(
            job_id=job_id,
            conversation_id=request.conversation_id,
            preview_url=artifact_url_by_hash(content_hash, "preview"),
            final_url=artifact_url_by_hash(content_hash, "final"),
        )
        return RenderQueueResponse(job_id=job_id, job=job)

    job = await get_job_store().create_queued_job(
        job_id=job_id, conversation_id=request.conversation_id
    )
    await enqueue_render_job(
        job_id=job_id,
        scene_path=str(scene_path),
        content_hash=content_hash,
        conversation_id=request.conversation_id,
        render_options=request.render_options,
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
