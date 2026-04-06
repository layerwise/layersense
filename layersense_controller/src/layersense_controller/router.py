import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from layersense_controller.cache import (
    hash_file,
    lookup_cached_artifacts,
    lookup_content_hash_for_scene,
    store_cached_artifacts,
)
from layersense_controller.config import settings
from layersense_controller.render import (
    RenderError,
    _raw_output_path,
    _scene_path_relative_to_scenes_dir,
    render_final,
    render_preview,
)
from layersense_controller.websocket_manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)


class RenderRequest(BaseModel):
    scene_path: str
    conversation_id: str


def _scene_uuid_from_scene_path(scene_path: Path) -> str:
    stem = scene_path.stem
    if stem.startswith("generated_"):
        generated_uuid = stem.removeprefix("generated_")
        if generated_uuid:
            return generated_uuid
    return stem


def _is_generated_scene_path(scene_path: Path) -> bool:
    return scene_path.stem.startswith("generated_")


def _artifact_url_by_hash(content_hash: str, kind: Literal["preview", "final"]) -> str:
    return f"/artifacts/by-hash/{content_hash}/{kind}"


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


def _scene_relative_artifact_path(path: Path) -> str:
    scenes_root = (settings.artifacts_dir / "scenes").resolve()
    return path.resolve().relative_to(scenes_root).as_posix()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


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
async def render(request: RenderRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    scene_path = Path(request.scene_path)

    if not scene_path.exists() or not scene_path.is_file():
        raise HTTPException(status_code=404, detail="Scene file not found")

    try:
        _scene_path_relative_to_scenes_dir(scene_path)
    except RenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content_hash = hash_file(scene_path)
    scene_uuid = _scene_uuid_from_scene_path(scene_path)
    cached = lookup_cached_artifacts(content_hash)

    if cached and cached["preview"] and cached["final"]:
        if cached["scene_uuid"] != scene_uuid:
            if not _is_generated_scene_path(scene_path):
                background_tasks.add_task(
                    _render_pipeline,
                    scene_path=scene_path,
                    content_hash=content_hash,
                    conversation_id=request.conversation_id,
                )
                return {"status": "queued"}

            store_cached_artifacts(
                content_hash=content_hash,
                scene_uuid=scene_uuid,
                scene_path=_scene_path_relative_to_scenes_dir(scene_path).as_posix(),
                preview=cached["preview"],
                final=cached["final"],
            )

        await manager.broadcast(
            {
                "type": "artifact_ready",
                "conversation_id": request.conversation_id,
                "preview_url": _artifact_url_by_hash(content_hash, "preview"),
                "final_url": _artifact_url_by_hash(content_hash, "final"),
            }
        )
        return {"status": "cached"}

    background_tasks.add_task(
        _render_pipeline,
        scene_path=scene_path,
        content_hash=content_hash,
        conversation_id=request.conversation_id,
    )
    return {"status": "queued"}


async def _render_pipeline(scene_path: Path, content_hash: str, conversation_id: str) -> None:
    cached = lookup_cached_artifacts(content_hash)
    scene_uuid = _scene_uuid_from_scene_path(scene_path)
    can_reuse_cached_hash = bool(cached) and (
        cached["scene_uuid"] == scene_uuid or _is_generated_scene_path(scene_path)
    )
    preview_cached = bool(can_reuse_cached_hash and cached and cached["preview"])
    final_cached = bool(can_reuse_cached_hash and cached and cached["final"])
    scene_relative_path = _scene_path_relative_to_scenes_dir(scene_path).as_posix()
    logger.info("render started for %s: %s", conversation_id, scene_path)

    try:
        preview_path = _raw_output_path(scene_path, "preview")
        if not preview_cached:
            preview_path = await render_preview(scene_path, content_hash)
            store_cached_artifacts(
                content_hash=content_hash,
                scene_uuid=scene_uuid,
                scene_path=scene_relative_path,
                preview=_scene_relative_artifact_path(preview_path),
            )
            logger.info("preview ready for %s: %s", conversation_id, preview_path)
        elif preview_path.exists():
            store_cached_artifacts(
                content_hash=content_hash,
                scene_uuid=scene_uuid,
                scene_path=scene_relative_path,
                preview=_scene_relative_artifact_path(preview_path),
            )
        if preview_path.exists():
            await manager.broadcast(
                {
                    "type": "preview_ready",
                    "conversation_id": conversation_id,
                    "url": _artifact_url_by_hash(content_hash, "preview"),
                }
            )

        final_path = _raw_output_path(scene_path, "final")
        if not final_cached:
            final_path = await render_final(scene_path, content_hash)
            store_cached_artifacts(
                content_hash=content_hash,
                scene_uuid=scene_uuid,
                scene_path=scene_relative_path,
                final=_scene_relative_artifact_path(final_path),
            )
            logger.info("render ready for %s: %s", conversation_id, final_path)
        elif final_path.exists():
            store_cached_artifacts(
                content_hash=content_hash,
                scene_uuid=scene_uuid,
                scene_path=scene_relative_path,
                final=_scene_relative_artifact_path(final_path),
            )
        if final_path.exists():
            await manager.broadcast(
                {
                    "type": "render_ready",
                    "conversation_id": conversation_id,
                    "url": _artifact_url_by_hash(content_hash, "final"),
                }
            )
    except RenderError as exc:
        logger.warning(
            "render failed for %s at %s: %s; stderr=%s",
            conversation_id,
            scene_path,
            str(exc),
            exc.stderr,
        )
        await manager.broadcast(
            {
                "type": "render_failed",
                "conversation_id": conversation_id,
                "error": str(exc),
                "stderr": exc.stderr,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("render failed for %s", conversation_id)
        await manager.broadcast(
            {
                "type": "render_failed",
                "conversation_id": conversation_id,
                "error": str(exc),
                "stderr": "",
            }
        )
