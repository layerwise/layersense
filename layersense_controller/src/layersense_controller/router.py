import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from layersense_controller.cache import final_artifact, hash_file, is_cached, preview_artifact
from layersense_controller.config import settings
from layersense_controller.render import RenderError, render_final, render_preview
from layersense_controller.websocket_manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)


class RenderRequest(BaseModel):
    scene_path: str
    conversation_id: str


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


@router.get("/artifacts/{filename}")
async def get_artifact(filename: str) -> FileResponse:
    artifact_path = settings.artifacts_dir / filename
    if not artifact_path.exists() or not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path=artifact_path, media_type="video/mp4", filename=filename)


@router.post("/render")
async def render(request: RenderRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    scene_path = Path(request.scene_path)

    if not scene_path.exists() or not scene_path.is_file():
        raise HTTPException(status_code=404, detail="Scene file not found")

    content_hash = hash_file(scene_path)
    preview_cached, final_cached = is_cached(content_hash)

    if preview_cached and final_cached:
        preview_url = f"/artifacts/{preview_artifact(content_hash).name}"
        final_url = f"/artifacts/{final_artifact(content_hash).name}"
        await manager.broadcast(
            {
                "type": "artifact_ready",
                "conversation_id": request.conversation_id,
                "preview_url": preview_url,
                "final_url": final_url,
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
    preview_cached, final_cached = is_cached(content_hash)
    logger.info("render started for %s: %s", conversation_id, scene_path)

    try:
        if not preview_cached:
            preview_path = await render_preview(scene_path, content_hash)
            logger.info("preview ready for %s: %s", conversation_id, preview_path)
            await manager.broadcast(
                {
                    "type": "preview_ready",
                    "conversation_id": conversation_id,
                    "url": f"/artifacts/{preview_path.name}",
                }
            )

        if not final_cached:
            final_path = await render_final(scene_path, content_hash)
            logger.info("render ready for %s: %s", conversation_id, final_path)
            await manager.broadcast(
                {
                    "type": "render_ready",
                    "conversation_id": conversation_id,
                    "url": f"/artifacts/{final_path.name}",
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
