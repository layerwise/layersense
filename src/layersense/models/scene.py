from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, constr

HexColor = Annotated[
    str,
    StringConstraints(
        pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"
    ),
]

type Shape = Literal[
    "rectangle",
    "circle",
    "ellipse",
    "freedraw",
]


class Element(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    type: Shape
    x: int  # px
    y: int  # px
    width: int  # px
    height: int  # px
    angle: float
    strokeColor: HexColor
    backgroundColor: HexColor | str
    fillStyle: str
    strokeWidth: int
    strokeStyle: str
    roughness: float
    opacity: float
    groupIds: list[str] = Field(exclude=True)  # exclude from serialize
    frameId: str = Field(exclude=True)  # exclude from serialize
    roundness: Any | None = None
    points: list[list[float]] | None = None


class AppState(BaseModel):
    gridSize: int
    gridStep: int
    gridModeEnabled: bool
    viewBackgroundColor: HexColor


class ExcalidrawScene(BaseModel):
    type: Literal["excalidraw"] = "excalidraw"
    version: int = 2
    source: str = "http://localhost:3000"
    elements: list[Element]
    appState: AppState
    files: dict[str, Any]


def validate_scene(payload: dict[str, Any]) -> ExcalidrawScene:
    return ExcalidrawScene.model_validate(payload)
