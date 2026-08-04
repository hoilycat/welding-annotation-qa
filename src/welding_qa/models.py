from __future__ import annotations

from dataclasses import dataclass, field
import math
from numbers import Real
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

        for field_name, coordinates in (("x", self.x), ("y", self.y)):
            normalized = []
            for index, value in enumerate(coordinates):
                if isinstance(value, bool) or not isinstance(value, Real):
                    raise ParsingError(
                        f"Polygon {field_name} coordinate at index {index} must be a number."
                    )
                try:
                    normalized_value = float(value)
                except OverflowError as exc:
                    raise ParsingError(
                        f"Polygon {field_name} coordinate at index {index} must be finite."
                    ) from exc
                if not math.isfinite(normalized_value):
                    raise ParsingError(
                        f"Polygon {field_name} coordinate at index {index} must be finite."
                    )
                normalized.append(normalized_value)
            object.__setattr__(self, field_name, tuple(normalized))


@dataclass
class DefectAnnotation:
    label_original: str
    label_canonical: str
    polygon: Polygon
    modality: str = "RT"
    extra_meta: dict[str, Any] = field(default_factory=dict)
