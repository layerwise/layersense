from pydantic import BaseModel, Field


class ConversationCreatedResponse(BaseModel):
    conversation_id: str = Field(description="A unique identifier for the conversation.")


class AnimationCreatedResponse(BaseModel):
    conversation_id: str = Field(description="Unique identifier for this animation session.")
    scene_path: str = Field(description="Absolute path to the generated Manim scene file.")


class AnimationInputs(BaseModel):
    prompt: str = Field(description="The prompt for the animation.")
    json_data: str = Field(description="The json data for the animation.")
