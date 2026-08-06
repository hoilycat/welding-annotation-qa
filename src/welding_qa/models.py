"""검증을 마친 Polygon과 용접 결함 annotation을 표현하는 핵심 모델 모듈."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from numbers import Real
from typing import Any


class ParsingError(ValueError):
    """입력 스키마나 좌표 검증이 실패했을 때 외부로 전달하는 공통 예외."""
    pass


@dataclass(frozen=True)
class Polygon:
    x: tuple[float, ...]
    y: tuple[float, ...]

    def __post_init__(self) -> None:
        # Polygon을 만들자마자 구조를 보장해 이후 코드가 좌표 개수를 재검사하지 않게 하는 코드
        if len(self.x) != len(self.y):
            raise ParsingError(
                f"x and y coordinate lengths mismatch: len(x)={len(self.x)}, len(y)={len(self.y)}"
            )
        if len(self.x) < 3:
            raise ParsingError(
                f"Polygon requires at least 3 vertices, got {len(self.x)}"
            )

        # bool은 int의 하위 타입이므로 숫자 검사에서 별도로 차단하는 코드
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
            # frozen dataclass 내부 값을 검증된 float tuple로 한 번만 정규화하는 코드
            object.__setattr__(self, field_name, tuple(normalized))

        # 길이가 0인 edge를 만드는 연속 중복점과 닫힘 중복점을 차단하는 검사
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
        """Polygon 좌표가 선택적으로 주어진 이미지 크기 안에 있는지 검사하는 함수."""
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
    """선택적인 이미지 크기를 검증하고 비교 가능한 float로 정규화하는 함수."""
    # annotation이 비어 있어도 이미지 메타데이터 자체는 항상 검증할 수 있게 분리한 코드
    normalized_width = (
        _normalize_image_dimension("width", width) if width is not None else None
    )
    normalized_height = (
        _normalize_image_dimension("height", height) if height is not None else None
    )
    return normalized_width, normalized_height


def _normalize_image_dimension(field_name: str, value: Any) -> float:
    # 좌표와 달리 이미지 크기는 0보다 커야 유효한 것으로 처리하는 검사
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
    """원본 라벨, canonical 라벨, Polygon과 부가 메타데이터를 묶는 모델."""

    label_original: str
    label_canonical: str
    polygon: Polygon
    modality: str = "RT"
    extra_meta: dict[str, Any] = field(default_factory=dict)
