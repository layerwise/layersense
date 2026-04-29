from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints

HexColor = Annotated[
    str,
    StringConstraints(
        pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"
    ),
]


class BaseElement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    x: float
    y: float
    width: float
    height: float
    angle: float
    strokeColor: HexColor
    backgroundColor: str
    fillStyle: str
    strokeWidth: int
    strokeStyle: str
    opacity: float


class RectangleElement(BaseElement):
    type: Literal["rectangle"]


class EllipseElement(BaseElement):
    type: Literal["ellipse"]


class FreedrawElement(BaseElement):
    type: Literal["freedraw"]
    points: list[list[float]]


NormalizedElement = Annotated[
    RectangleElement | EllipseElement | FreedrawElement,
    Field(discriminator="type"),
]


class NormalizedAppState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    viewBackgroundColor: HexColor | None = None


class NormalizedFiles(RootModel[dict[str, object]]):
    pass


class NormalizedScene(BaseModel):
    elements: list[NormalizedElement]
    appState: NormalizedAppState
    files: NormalizedFiles
