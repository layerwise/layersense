from sqlalchemy import select
from sqlalchemy.orm import Session

from layersense_persistence.models import Render, utc_now_iso
from layersense_persistence.repositories._common import new_id


class RendersRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        scene_id: str,
        content_hash: str,
        status: str = "generating",
        parent_render_id: str | None = None,
        refinement_prompt: str = "",
        scene_py_artifact_key: str | None = None,
        preview_artifact_key: str | None = None,
        final_artifact_key: str | None = None,
        log_artifact_key: str | None = None,
        cli_flags_json: str = "{}",
        conversation_id: str | None = None,
        error_message: str | None = None,
    ) -> Render:
        render = Render(
            id=new_id(),
            scene_id=scene_id,
            parent_render_id=parent_render_id,
            refinement_prompt=refinement_prompt,
            content_hash=content_hash,
            status=status,
            scene_py_artifact_key=scene_py_artifact_key,
            preview_artifact_key=preview_artifact_key,
            final_artifact_key=final_artifact_key,
            log_artifact_key=log_artifact_key,
            cli_flags_json=cli_flags_json,
            conversation_id=conversation_id,
            error_message=error_message,
        )
        self.session.add(render)
        self.session.flush()
        return render

    def get(self, render_id: str) -> Render | None:
        return self.session.get(Render, render_id)

    def list_by_scene(self, scene_id: str) -> list[Render]:
        return list(
            self.session.scalars(
                select(Render)
                .where(Render.scene_id == scene_id)
                .order_by(Render.created_at.desc())
            )
        )

    def list_by_content_hash(self, content_hash: str) -> list[Render]:
        return list(
            self.session.scalars(
                select(Render)
                .where(Render.content_hash == content_hash)
                .order_by(Render.created_at.desc())
            )
        )

    def update_status(
        self,
        render_id: str,
        *,
        status: str,
        scene_py_artifact_key: str | None = None,
        preview_artifact_key: str | None = None,
        final_artifact_key: str | None = None,
        log_artifact_key: str | None = None,
        error_message: str | None = None,
    ) -> Render:
        render = self._require(render_id)
        render.status = status
        if scene_py_artifact_key is not None:
            render.scene_py_artifact_key = scene_py_artifact_key
        if preview_artifact_key is not None:
            render.preview_artifact_key = preview_artifact_key
        if final_artifact_key is not None:
            render.final_artifact_key = final_artifact_key
        if log_artifact_key is not None:
            render.log_artifact_key = log_artifact_key
        if error_message is not None:
            render.error_message = error_message
        render.updated_at = utc_now_iso()
        self.session.flush()
        return render

    def delete(self, render_id: str) -> None:
        render = self._require(render_id)
        self.session.delete(render)
        self.session.flush()

    def _require(self, render_id: str) -> Render:
        render = self.get(render_id)
        if render is None:
            raise KeyError(render_id)
        return render
