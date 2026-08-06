"""내부 annotation 모델과 CVAT polygon payload를 양방향 변환하는 모듈."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .models import DefectAnnotation, ParsingError, Polygon
from .taxonomy import TaxonomyConfig


def polygon_to_cvat_points(polygon: Polygon) -> list[float]:
    """Polygon의 x/y tuple을 CVAT의 평탄한 좌표 배열로 바꾸는 함수."""
    if not isinstance(polygon, Polygon):
        raise ParsingError("CVAT polygon conversion requires a Polygon instance.")

    return [coordinate for point in zip(polygon.x, polygon.y) for coordinate in point]


def polygon_from_cvat_points(points: Sequence[Any]) -> Polygon:
    """CVAT의 평탄한 좌표 배열을 검증된 Polygon으로 바꾸는 함수."""
    if isinstance(points, (str, bytes)) or not isinstance(points, Sequence):
        raise ParsingError("CVAT polygon 'points' must be a list or tuple.")
    if len(points) % 2 != 0:
        raise ParsingError(
            f"CVAT polygon 'points' must contain x/y pairs, got {len(points)} values."
        )

    # 짝수/홀수 위치를 각각 x/y로 나눠 Polygon 공통 검증을 재사용하는 코드
    return Polygon(x=tuple(points[0::2]), y=tuple(points[1::2]))


def annotation_to_cvat_shape(
    annotation: DefectAnnotation,
    label_id: int,
    *,
    frame: int = 0,
) -> dict[str, Any]:
    """annotation 하나를 CVAT LabeledShapeRequest 형태로 바꾸는 함수."""
    if not isinstance(annotation, DefectAnnotation):
        raise ParsingError("CVAT shape conversion requires a DefectAnnotation instance.")

    _validate_non_negative_integer("label_id", label_id)
    _validate_non_negative_integer("frame", frame)

    # CVAT polygon 생성 API가 요구하는 기본 shape 필드를 채우는 payload
    return {
        "type": "polygon",
        "frame": frame,
        "label_id": label_id,
        "points": polygon_to_cvat_points(annotation.polygon),
        "occluded": False,
        "outside": False,
        "z_order": 0,
        "rotation": 0.0,
        "group": 0,
        "source": "manual",
        "attributes": [],
    }


def annotations_to_cvat_shapes(
    annotations: Iterable[DefectAnnotation],
    label_ids: Mapping[str, int],
    *,
    frame: int = 0,
) -> list[dict[str, Any]]:
    """canonical slug와 CVAT label ID의 매핑을 사용해 여러 annotation을 변환하는 함수."""
    shapes: list[dict[str, Any]] = []
    for index, annotation in enumerate(annotations):
        if not isinstance(annotation, DefectAnnotation):
            raise ParsingError(
                f"Annotation at index {index} must be a DefectAnnotation instance."
            )

        # 서버 프로젝트마다 label ID가 달라질 수 있어 호출자가 전달한 매핑을 사용하는 코드
        canonical_slug = annotation.label_canonical
        if canonical_slug not in label_ids:
            raise ParsingError(
                f"Annotation at index {index}: no CVAT label ID configured for "
                f"canonical label '{canonical_slug}'."
            )

        try:
            shape = annotation_to_cvat_shape(
                annotation,
                label_ids[canonical_slug],
                frame=frame,
            )
        except ParsingError as exc:
            raise ParsingError(f"Annotation at index {index}: {exc}") from exc
        shapes.append(shape)

    return shapes


def cvat_shape_to_annotation(
    shape: Mapping[str, Any],
    label_names: Mapping[int, str],
    taxonomy: TaxonomyConfig,
    *,
    modality: str = "RT",
) -> DefectAnnotation:
    """CVAT polygon shape 하나를 검증된 내부 annotation으로 바꾸는 함수."""
    if not isinstance(shape, Mapping):
        raise ParsingError("CVAT shape must be a dictionary object.")
    if shape.get("type") != "polygon":
        raise ParsingError("CVAT shape field 'type' must be 'polygon'.")

    label_id = shape.get("label_id")
    _validate_non_negative_integer("label_id", label_id)
    if label_id not in label_names:
        raise ParsingError(f"Unknown CVAT label ID '{label_id}'.")

    frame = shape.get("frame")
    _validate_non_negative_integer("frame", frame)

    if not isinstance(modality, str):
        raise ParsingError("CVAT annotation modality must be a string.")
    if not modality.strip():
        raise ParsingError("CVAT annotation modality must not be empty.")

    raw_label = label_names[label_id]
    if not isinstance(raw_label, str) or not raw_label.strip():
        raise ParsingError(f"CVAT label name for ID '{label_id}' must be a non-empty string.")

    # CVAT label 이름도 taxonomy를 거쳐 같은 canonical 기준으로 통일하는 코드
    try:
        canonical_slug = taxonomy.get_canonical_slug(raw_label)
    except ValueError as exc:
        raise ParsingError(f"CVAT label ID '{label_id}' has invalid label: {exc}") from exc
    if not taxonomy.is_modality_allowed(canonical_slug, modality):
        raise ParsingError(
            f"Modality '{modality}' is not allowed for canonical label "
            f"'{canonical_slug}'."
        )

    if "points" not in shape:
        raise ParsingError("CVAT polygon shape missing required 'points' field.")
    try:
        polygon = polygon_from_cvat_points(shape["points"])
    except ParsingError as exc:
        raise ParsingError(f"CVAT polygon shape: {exc}") from exc

    # 다시 CVAT로 추적하거나 디버깅할 때 필요한 서버 메타데이터만 선별해 보존하는 코드
    cvat_meta = {
        key: shape[key]
        for key in (
            "id",
            "frame",
            "label_id",
            "group",
            "source",
            "occluded",
            "outside",
            "z_order",
            "rotation",
        )
        if key in shape
    }

    return DefectAnnotation(
        label_original=raw_label,
        label_canonical=canonical_slug,
        polygon=polygon,
        modality=modality,
        extra_meta={"cvat": cvat_meta},
    )


def cvat_shapes_to_annotations(
    shapes: Iterable[Mapping[str, Any]],
    label_names: Mapping[int, str],
    taxonomy: TaxonomyConfig,
    *,
    modality: str = "RT",
) -> list[DefectAnnotation]:
    """여러 CVAT shape를 변환하고 실패 메시지에 shape 인덱스를 붙이는 함수."""
    annotations: list[DefectAnnotation] = []
    for index, shape in enumerate(shapes):
        try:
            annotation = cvat_shape_to_annotation(
                shape,
                label_names,
                taxonomy,
                modality=modality,
            )
        except ParsingError as exc:
            raise ParsingError(f"CVAT shape at index {index}: {exc}") from exc
        annotations.append(annotation)

    return annotations


def _validate_non_negative_integer(field_name: str, value: Any) -> None:
    # bool이 int로 통과하는 Python 특성을 막으면서 CVAT ID와 frame 범위를 확인하는 검사
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ParsingError(f"CVAT shape field '{field_name}' must be a non-negative integer.")
