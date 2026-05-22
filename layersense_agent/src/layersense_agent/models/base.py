from typing import Any

from pydantic import BaseModel, Field


class ConversationCreatedResponse(BaseModel):
    conversation_id: str = Field(description="A unique identifier for the conversation.")


class AnimationCreatedResponse(BaseModel):
    conversation_id: str = Field(description="Unique identifier for this animation session.")
    source_code: str = Field(description="Generated Manim scene source code.")
    content_hash: str = Field(description="SHA-256 hash of the generated source code.")


class AnimationInputs(BaseModel):
    prompt: str = Field(description="The prompt for the animation.")
    scene: dict[str, Any] = Field(description="The Excalidraw scene snapshot for the animation.")
