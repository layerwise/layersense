from pydantic import BaseModel, Field


class ConversationCreatedResponse(BaseModel):
    conversation_id: str = Field(description="A unique identifier for the conversation.")


class AnimationInputs(BaseModel):
    prompt: str = Field(description="The prompt for the animation.")
    json_data: str = Field(description="The json data for the animation.")
