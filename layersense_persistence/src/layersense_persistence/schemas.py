from typing import Literal

from pydantic import BaseModel, ConfigDict

RenderStatus = Literal["generating", "queued", "preview_ready", "final_ready", "failed"]


class ProjectCreate(BaseModel):
    name: str
    default_render_config_json: str = "{}"


class ProjectUpdate(BaseModel):
    name: str | None = None
    default_render_config_json: str | None = None


class ProjectRead(BaseModel):
    id: str
    name: str
    slug: str
    default_render_config_json: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class FrameCreate(BaseModel):
    excalidraw_frame_id: str
    order_index: int | None = None
    prompt_augmentation: str = ""


class FrameUpdate(BaseModel):
    prompt_augmentation: str | None = None


class FrameRead(BaseModel):
    id: str
    scene_id: str
    order_index: int
    excalidraw_frame_id: str
    prompt_augmentation: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class SceneCreate(BaseModel):
    name: str
    order_index: int | None = None
    prompt: str = ""
    excalidraw_scene_json: str = "{}"


class SceneUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    excalidraw_scene_json: str | None = None


class SceneRead(BaseModel):
    id: str
    project_id: str
    name: str
    order_index: int
    prompt: str
    excalidraw_scene_json: str
    current_render_id: str | None
    thumbnail_artifact_key: str | None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class SceneWithFramesRead(SceneRead):
    frames: list[FrameRead]


class RenderCreate(BaseModel):
    content_hash: str
    status: RenderStatus = "generating"
    parent_render_id: str | None = None
    refinement_prompt: str = ""
    scene_py_artifact_key: str | None = None
    preview_artifact_key: str | None = None
    final_artifact_key: str | None = None
    log_artifact_key: str | None = None
    cli_flags_json: str = "{}"
    conversation_id: str | None = None
    error_message: str | None = None


class RenderUpdate(BaseModel):
    status: RenderStatus | None = None
    scene_py_artifact_key: str | None = None
    preview_artifact_key: str | None = None
    final_artifact_key: str | None = None
    log_artifact_key: str | None = None
    error_message: str | None = None


class RenderRead(BaseModel):
    id: str
    scene_id: str
    parent_render_id: str | None
    refinement_prompt: str
    content_hash: str
    status: RenderStatus
    scene_py_artifact_key: str | None
    preview_artifact_key: str | None
    final_artifact_key: str | None
    log_artifact_key: str | None
    cli_flags_json: str
    conversation_id: str | None
    error_message: str | None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)
