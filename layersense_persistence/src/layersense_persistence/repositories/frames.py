from sqlalchemy import select
from sqlalchemy.orm import Session

from layersense_persistence.models import Frame, utc_now_iso
from layersense_persistence.repositories._common import new_id, next_order_index


class FramesRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        scene_id: str,
        excalidraw_frame_id: str,
        order_index: int | None = None,
        prompt_augmentation: str = "",
    ) -> Frame:
        frame = Frame(
            id=new_id(),
            scene_id=scene_id,
            order_index=(
                next_order_index(self.session, Frame, "scene_id", scene_id)
                if order_index is None
                else order_index
            ),
            excalidraw_frame_id=excalidraw_frame_id,
            prompt_augmentation=prompt_augmentation,
        )
        self.session.add(frame)
        self.session.flush()
        return frame

    def get(self, frame_id: str) -> Frame | None:
        return self.session.get(Frame, frame_id)

    def list_by_scene(self, scene_id: str) -> list[Frame]:
        return list(
            self.session.scalars(
                select(Frame).where(Frame.scene_id == scene_id).order_by(Frame.order_index)
            )
        )

    def update(
        self,
        frame_id: str,
        *,
        prompt_augmentation: str | None = None,
        excalidraw_frame_id: str | None = None,
    ) -> Frame:
        frame = self._require(frame_id)
        if prompt_augmentation is not None:
            frame.prompt_augmentation = prompt_augmentation
        if excalidraw_frame_id is not None:
            frame.excalidraw_frame_id = excalidraw_frame_id
        frame.updated_at = utc_now_iso()
        self.session.flush()
        return frame

    def reorder(self, scene_id: str, ordered_ids: list[str]) -> None:
        frames = self.list_by_scene(scene_id)
        frames_by_id = {frame.id: frame for frame in frames}
        if set(frames_by_id) != set(ordered_ids):
            raise ValueError("ordered_ids must contain exactly this scene's frame ids")
        offset = len(ordered_ids)
        for index, frame_id in enumerate(ordered_ids):
            frames_by_id[frame_id].order_index = offset + index
        self.session.flush()
        for index, frame_id in enumerate(ordered_ids):
            frames_by_id[frame_id].order_index = index
            frames_by_id[frame_id].updated_at = utc_now_iso()
        self.session.flush()

    def delete(self, frame_id: str) -> None:
        frame = self._require(frame_id)
        self.session.delete(frame)
        self.session.flush()

    def _require(self, frame_id: str) -> Frame:
        frame = self.get(frame_id)
        if frame is None:
            raise KeyError(frame_id)
        return frame
