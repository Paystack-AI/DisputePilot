from typing import Literal

from pydantic import BaseModel

ReadinessLabel = Literal["well_defended", "moderate", "vulnerable"]


class ReadinessComponent(BaseModel):
    key: str
    label: str
    status: Literal["available", "missing"]
    points: int
    max_points: int
    suggestion: str | None = None


class Readiness(BaseModel):
    score: int
    label: ReadinessLabel


class ReadinessDetail(Readiness):
    components: list[ReadinessComponent]
