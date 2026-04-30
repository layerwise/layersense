from pydantic import BaseModel, Field


class RenderOptions(BaseModel):
    background_color: str | None = Field(
        default=None,
        description="Optional background color override for rendering.",
    )
