from layersense_persistence.database import get_session
from layersense_persistence.repositories import RendersRepository

from layersense_controller.artifacts import (
    get_object_store,
    materialize_scene_source_for_manim,
    store_render_outputs,
)
from layersense_controller.broker import broker, get_job_store
from layersense_controller.render import CLIFlags, RenderError, render_final, render_preview
from layersense_controller.render_runtime import artifact_url_by_hash


async def _run_render_pipeline(
    job_id: str,
    render_id: str,
    content_hash: str,
    cli_flags: CLIFlags | None = None,
) -> None:
    preview_url = artifact_url_by_hash(content_hash, "preview")
    final_url = artifact_url_by_hash(content_hash, "final")
    preview_available = False
    object_store = get_object_store()

    try:
        with get_session() as session:
            render = RendersRepository(session).get(render_id)
            if render is None or render.scene_py_artifact_key is None:
                raise RenderError("render source is missing", "")
            source_key = render.scene_py_artifact_key

        with materialize_scene_source_for_manim(
            object_store, source_key=source_key, render_id=render_id
        ) as source_file_path:
            await get_job_store().update_job(job_id, "preview_rendering")
            preview_path = await render_preview(source_file_path, content_hash, cli_flags)
            preview_available = True
            with get_session() as session:
                store_render_outputs(
                    session,
                    object_store,
                    render_id=render_id,
                    content_hash=content_hash,
                    preview_path=preview_path,
                )
            await get_job_store().update_job(
                job_id,
                "waiting_for_final",
                preview_url=preview_url,
            )
            await get_job_store().update_job(job_id, "final_rendering")
            final_path = await render_final(source_file_path, content_hash, cli_flags)
            with get_session() as session:
                store_render_outputs(
                    session,
                    object_store,
                    render_id=render_id,
                    content_hash=content_hash,
                    final_path=final_path,
                    log_text="",
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
        with get_session() as session:
            RendersRepository(session).update_status(
                render_id, status="failed", error_message=str(exc)
            )
    except Exception as exc:  # noqa: BLE001
        changes = {"error": str(exc), "stderr": ""}
        if preview_available:
            changes["preview_url"] = preview_url
        await get_job_store().update_job(job_id, "failed", **changes)
        with get_session() as session:
            RendersRepository(session).update_status(
                render_id, status="failed", error_message=str(exc)
            )


@broker.task
async def run_render_job(
    job_id: str,
    render_id: str,
    content_hash: str,
    cli_flags: dict[str, object] | None = None,
) -> None:
    await _run_render_pipeline(
        job_id=job_id,
        render_id=render_id,
        content_hash=content_hash,
        cli_flags=CLIFlags.model_validate(cli_flags) if cli_flags is not None else None,
    )
