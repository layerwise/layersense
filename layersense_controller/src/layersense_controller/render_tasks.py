from pathlib import Path

from layersense_domain.models import RenderOptions

from layersense_controller.broker import broker, get_job_store
from layersense_controller.cache import store_cached_artifacts
from layersense_controller.config import settings
from layersense_controller.render import RenderError, render_final, render_preview
from layersense_controller.render_runtime import (
    artifact_url_by_hash,
    scene_relative_artifact_path,
    scene_uuid_from_scene_path,
)


async def _run_render_pipeline(
    job_id: str,
    scene_path: Path,
    content_hash: str,
    conversation_id: str,
    render_options: RenderOptions | None = None,
) -> None:
    del conversation_id

    preview_url = artifact_url_by_hash(content_hash, "preview")
    final_url = artifact_url_by_hash(content_hash, "final")
    scene_relative_path = (
        scene_path.resolve().relative_to(settings.scenes_dir.resolve()).as_posix()
    )
    preview_available = False

    try:
        await get_job_store().update_job(job_id, "preview_rendering")
        preview_path = await render_preview(scene_path, content_hash, render_options)
        store_cached_artifacts(
            content_hash=content_hash,
            scene_uuid=scene_uuid_from_scene_path(scene_path),
            scene_path=scene_relative_path,
            preview=scene_relative_artifact_path(preview_path),
        )
        preview_available = True
        await get_job_store().update_job(
            job_id,
            "waiting_for_final",
            preview_url=preview_url,
        )
        await get_job_store().update_job(job_id, "final_rendering")
        final_path = await render_final(scene_path, content_hash, render_options)
        store_cached_artifacts(
            content_hash=content_hash,
            scene_uuid=scene_uuid_from_scene_path(scene_path),
            scene_path=scene_relative_path,
            final=scene_relative_artifact_path(final_path),
        )
        await get_job_store().update_job(
            job_id,
            "succeeded",
            preview_url=preview_url,
            final_url=final_url,
        )
    except RenderError as exc:
        changes: dict[str, str] = {"error": str(exc), "stderr": exc.stderr}
        if preview_available:
            changes["preview_url"] = preview_url
        await get_job_store().update_job(job_id, "failed", **changes)
    except Exception as exc:  # noqa: BLE001
        changes = {"error": str(exc), "stderr": ""}
        if preview_available:
            changes["preview_url"] = preview_url
        await get_job_store().update_job(job_id, "failed", **changes)


@broker.task
async def run_render_job(
    job_id: str,
    scene_path: str,
    content_hash: str,
    conversation_id: str,
    render_options: dict[str, str | None] | None = None,
) -> None:
    await _run_render_pipeline(
        job_id=job_id,
        scene_path=Path(scene_path),
        content_hash=content_hash,
        conversation_id=conversation_id,
        render_options=(
            RenderOptions.model_validate(render_options)
            if render_options is not None
            else None
        ),
    )
