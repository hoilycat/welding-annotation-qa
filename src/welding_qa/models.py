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

        # 좌표 크기를 정규화해 큰 값의 곱셈 overflow 없이 면적과 교차를 검사하는 코드
        geometry_points = _normalize_geometry_points(points)
        geometry_tolerance = _geometry_tolerance(geometry_points)
        if _all_points_collinear(geometry_points, geometry_tolerance):
            raise ParsingError("Polygon area is zero or too small.")
        _validate_non_self_intersecting(geometry_points, geometry_tolerance)

        # shoelace 공식의 부호는 방향만 나타내므로 절댓값으로 면적 0 여부를 확인하는 검사
        signed_double_area = _shoelace_signed_double_area(geometry_points)
        if math.isclose(
            signed_double_area,
            0.0,
            rel_tol=0.0,
            abs_tol=geometry_tolerance,
        ):
            raise ParsingError("Polygon area is zero or too small.")

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


def _normalize_geometry_points(
    points: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    """좌표를 -1~1 범위로 축소해 기하 연산 overflow를 막는 함수."""
    coordinate_scale = max(max(abs(x), abs(y)) for x, y in points)
    if coordinate_scale == 0.0:
        return points
    return tuple((x / coordinate_scale, y / coordinate_scale) for x, y in points)


def _geometry_tolerance(points: tuple[tuple[float, float], ...]) -> float:
    """Polygon 범위에 비례하는 면적·orientation 비교 tolerance를 만드는 함수."""
    xs, ys = zip(*points)
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    return span * span * 1e-12


def _shoelace_signed_double_area(
    points: tuple[tuple[float, float], ...],
) -> float:
    """Shoelace 공식으로 방향 부호가 포함된 면적의 두 배를 계산하는 함수."""
    # 첫 점을 원점으로 옮겨 큰 공통 offset에서 생기는 cancellation을 줄이는 코드
    origin_x, origin_y = points[0]
    translated = tuple((x - origin_x, y - origin_y) for x, y in points)
    return math.fsum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(
            translated,
            translated[1:] + translated[:1],
        )
    )


def _all_points_collinear(
    points: tuple[tuple[float, float], ...],
    tolerance: float,
) -> bool:
    """가장 멀리 떨어진 축의 두 점을 기준으로 모든 꼭짓점이 일직선인지 확인하는 함수."""
    min_x_point = min(points, key=lambda point: point[0])
    max_x_point = max(points, key=lambda point: point[0])
    min_y_point = min(points, key=lambda point: point[1])
    max_y_point = max(points, key=lambda point: point[1])
    if max_x_point[0] - min_x_point[0] >= max_y_point[1] - min_y_point[1]:
        baseline_start, baseline_end = min_x_point, max_x_point
    else:
        baseline_start, baseline_end = min_y_point, max_y_point

    return all(
        _orientation(baseline_start, baseline_end, point, tolerance) == 0
        for point in points
    )


def _validate_non_self_intersecting(
    points: tuple[tuple[float, float], ...],
    tolerance: float,
) -> None:
    """서로 인접하지 않은 모든 변 쌍이 만나지 않는지 확인하는 함수."""
    edge_count = len(points)
    for first_index in range(edge_count):
        first_start = points[first_index]
        first_end = points[(first_index + 1) % edge_count]

        for second_index in range(first_index + 1, edge_count):
            # 연속 변과 첫 변·마지막 변은 정상적으로 한 꼭짓점을 공유하는 인접 변
            if second_index == first_index + 1 or (
                first_index == 0 and second_index == edge_count - 1
            ):
                continue

            second_start = points[second_index]
            second_end = points[(second_index + 1) % edge_count]
            if _segments_intersect(
                first_start,
                first_end,
                second_start,
                second_end,
                tolerance,
            ):
                raise ParsingError(
                    "Polygon has self-intersection between non-adjacent edges "
                    f"{first_index}-{(first_index + 1) % edge_count} and "
                    f"{second_index}-{(second_index + 1) % edge_count}."
                )


def _segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
    tolerance: float,
) -> bool:
    """교차·끝점 접촉·일부 겹침을 모두 선분 교차로 판단하는 함수."""
    orientations = (
        _orientation(first_start, first_end, second_start, tolerance),
        _orientation(first_start, first_end, second_end, tolerance),
        _orientation(second_start, second_end, first_start, tolerance),
        _orientation(second_start, second_end, first_end, tolerance),
    )
    first_to_second_start, first_to_second_end, second_to_first_start, second_to_first_end = (
        orientations
    )

    if (
        first_to_second_start * first_to_second_end < 0
        and second_to_first_start * second_to_first_end < 0
    ):
        return True

    return (
        first_to_second_start == 0
        and _point_on_segment(second_start, first_start, first_end, tolerance)
        or first_to_second_end == 0
        and _point_on_segment(second_end, first_start, first_end, tolerance)
        or second_to_first_start == 0
        and _point_on_segment(first_start, second_start, second_end, tolerance)
        or second_to_first_end == 0
        and _point_on_segment(first_end, second_start, second_end, tolerance)
    )


def _orientation(
    start: tuple[float, float],
    end: tuple[float, float],
    point: tuple[float, float],
    tolerance: float,
) -> int:
    """세 점의 방향을 반시계 1, 시계 -1, 거의 일직선 0으로 분류하는 함수."""
    cross_product = (
        (end[0] - start[0]) * (point[1] - start[1])
        - (end[1] - start[1]) * (point[0] - start[0])
    )
    if math.isclose(cross_product, 0.0, rel_tol=0.0, abs_tol=tolerance):
        return 0
    return 1 if cross_product > 0.0 else -1


def _point_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
    tolerance: float,
) -> bool:
    """거의 일직선인 점이 선분의 bounding box 안에 있는지 확인하는 함수."""
    # 면적 단위 tolerance를 같은 상대 정밀도의 좌표 단위 tolerance로 바꾸는 코드
    linear_tolerance = math.sqrt(tolerance) * 1e-6
    return (
        min(start[0], end[0]) - linear_tolerance
        <= point[0]
        <= max(start[0], end[0]) + linear_tolerance
        and min(start[1], end[1]) - linear_tolerance
        <= point[1]
        <= max(start[1], end[1]) + linear_tolerance
    )


@dataclass
class DefectAnnotation:
    """원본 라벨, canonical 라벨, Polygon과 부가 메타데이터를 묶는 모델."""

    label_original: str
    label_canonical: str
    polygon: Polygon
    modality: str = "RT"
    extra_meta: dict[str, Any] = field(default_factory=dict)
