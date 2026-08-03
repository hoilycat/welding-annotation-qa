from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ParsingError(ValueError):
    """Raised when JSON annotation schema parsing or coordinate validation fails."""
    pass


@dataclass(frozen=True)
class Polygon:
    x: tuple[float, ...]
    y: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.x) != len(self.y):
            raise ParsingError(
                f"x and y coordinate lengths mismatch: len(x)={len(self.x)}, len(y)={len(self.y)}"
            )
        if len(self.x) < 3:
            raise ParsingError(
                f"Polygon requires at least 3 vertices, got {len(self.x)}"
            )


@dataclass
class DefectAnnotation:
    label_original: str
    label_canonical: str
    polygon: Polygon
    modality: str = "RT"
    extra_meta: dict[str, Any] = field(default_factory=dict)
