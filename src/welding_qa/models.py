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

        points = tuple(zip(self.x, self.y))
        for index in range(1, len(points)):
            if points[index] == points[index - 1]:
                raise ParsingError(
                    f"Polygon has consecutive duplicate vertices at indices "
                    f"{index - 1} and {index}."
                )
        if points[-1] == points[0]:
            raise ParsingError(
                f"Polygon repeats its first vertex at closing index {len(points) - 1}."
            )

    def validate_image_bounds(
        self,
        *,
        width: Any = None,
        height: Any = None,
    ) -> None:
        """Ensure polygon coordinates fit dimensions supplied by image metadata."""
        normalized_width, normalized_height = validate_image_dimensions(
            width=width,
            height=height,
        )
        for field_name, coordinates, normalized_dimension in (
            ("x", self.x, normalized_width),
            ("y", self.y, normalized_height),
        ):
            if normalized_dimension is None:
                continue

            for index, coordinate in enumerate(coordinates):
                if coordinate < 0 or coordinate > normalized_dimension:
                    raise ParsingError(
                        f"Polygon {field_name} coordinate at index {index} "
                        f"is outside image bounds [0, {normalized_dimension:g}]."
                    )


def validate_image_dimensions(
    *,
    width: Any = None,
    height: Any = None,
) -> tuple[float | None, float | None]:
    """Validate optional image dimensions and return normalized numeric values."""
    normalized_width = (
        _normalize_image_dimension("width", width) if width is not None else None
    )
    normalized_height = (
        _normalize_image_dimension("height", height) if height is not None else None
    )
    return normalized_width, normalized_height


def _normalize_image_dimension(field_name: str, value: Any) -> float:
    error_message = f"Image {field_name} must be a positive finite number."
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ParsingError(error_message)
    try:
        normalized_value = float(value)
    except OverflowError as exc:
        raise ParsingError(error_message) from exc
    if not math.isfinite(normalized_value) or normalized_value <= 0:
        raise ParsingError(error_message)
    return normalized_value


@dataclass
class DefectAnnotation:
    label_original: str
    label_canonical: str
    polygon: Polygon
    modality: str = "RT"
    extra_meta: dict[str, Any] = field(default_factory=dict)
