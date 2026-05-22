from sqlalchemy import select
from sqlalchemy.orm import Session

from layersense_persistence.models import Scene, utc_now_iso
from layersense_persistence.repositories._common import new_id, next_order_index


class ScenesRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        project_id: str,
        name: str,
        order_index: int | None = None,
        prompt: str = "",
        excalidraw_scene_json: str = "{}",
    ) -> Scene:
        scene = Scene(
            id=new_id(),
            project_id=project_id,
            name=name,
            order_index=(
                next_order_index(self.session, Scene, "project_id", project_id)
                if order_index is None
                else order_index
            ),
            prompt=prompt,
            excalidraw_scene_json=excalidraw_scene_json,
        )
        self.session.add(scene)
        self.session.flush()
        return scene

    def get(self, scene_id: str) -> Scene | None:
        return self.session.get(Scene, scene_id)

    def list_by_project(self, project_id: str) -> list[Scene]:
        return list(
            self.session.scalars(
                select(Scene).where(Scene.project_id == project_id).order_by(Scene.order_index)
            )
        )

    def update(
        self,
        scene_id: str,
        *,
        prompt: str | None = None,
        excalidraw_scene_json: str | None = None,
        name: str | None = None,
        thumbnail_artifact_key: str | None = None,
    ) -> Scene:
        scene = self._require(scene_id)
        if prompt is not None:
            scene.prompt = prompt
        if excalidraw_scene_json is not None:
            scene.excalidraw_scene_json = excalidraw_scene_json
        if name is not None:
            scene.name = name
        if thumbnail_artifact_key is not None:
            scene.thumbnail_artifact_key = thumbnail_artifact_key
        scene.updated_at = utc_now_iso()
        self.session.flush()
        return scene

    def reorder(self, project_id: str, ordered_ids: list[str]) -> None:
        scenes = self.list_by_project(project_id)
        scenes_by_id = {scene.id: scene for scene in scenes}
        if set(scenes_by_id) != set(ordered_ids):
            raise ValueError("ordered_ids must contain exactly this project's scene ids")
        offset = len(ordered_ids)
        for index, scene_id in enumerate(ordered_ids):
            scenes_by_id[scene_id].order_index = offset + index
        self.session.flush()
        for index, scene_id in enumerate(ordered_ids):
            scenes_by_id[scene_id].order_index = index
            scenes_by_id[scene_id].updated_at = utc_now_iso()
        self.session.flush()

    def set_current_render(self, scene_id: str, render_id: str | None) -> Scene:
        scene = self._require(scene_id)
        scene.current_render_id = render_id
        scene.updated_at = utc_now_iso()
        self.session.flush()
        return scene

    def delete(self, scene_id: str) -> None:
        scene = self._require(scene_id)
        self.session.delete(scene)
        self.session.flush()

    def _require(self, scene_id: str) -> Scene:
        scene = self.get(scene_id)
        if scene is None:
            raise KeyError(scene_id)
        return scene
