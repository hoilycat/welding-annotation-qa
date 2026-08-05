from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .models import DefectAnnotation, ParsingError, Polygon
from .taxonomy import TaxonomyConfig


def polygon_to_cvat_points(polygon: Polygon) -> list[float]:
    """Flatten a polygon into CVAT's ``[x1, y1, x2, y2, ...]`` format."""
    if not isinstance(polygon, Polygon):
        raise ParsingError("CVAT polygon conversion requires a Polygon instance.")

    return [coordinate for point in zip(polygon.x, polygon.y) for coordinate in point]


def polygon_from_cvat_points(points: Sequence[Any]) -> Polygon:
    """Build a validated polygon from CVAT's flattened point representation."""
    if isinstance(points, (str, bytes)) or not isinstance(points, Sequence):
        raise ParsingError("CVAT polygon 'points' must be a list or tuple.")
    if len(points) % 2 != 0:
        raise ParsingError(
            f"CVAT polygon 'points' must contain x/y pairs, got {len(points)} values."
        )

    return Polygon(x=tuple(points[0::2]), y=tuple(points[1::2]))


def annotation_to_cvat_shape(
    annotation: DefectAnnotation,
    label_id: int,
    *,
    frame: int = 0,
) -> dict[str, Any]:
    """Convert one defect annotation to a CVAT ``LabeledShapeRequest`` payload."""
    if not isinstance(annotation, DefectAnnotation):
        raise ParsingError("CVAT shape conversion requires a DefectAnnotation instance.")

    _validate_non_negative_integer("label_id", label_id)
    _validate_non_negative_integer("frame", frame)

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
    """Convert annotations using canonical-slug-to-CVAT-label-ID mapping."""
    shapes: list[dict[str, Any]] = []
    for index, annotation in enumerate(annotations):
        if not isinstance(annotation, DefectAnnotation):
            raise ParsingError(
                f"Annotation at index {index} must be a DefectAnnotation instance."
            )

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
    """Convert one CVAT polygon shape into a validated defect annotation."""
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
    """Convert CVAT polygon shapes while adding the failing shape index to errors."""
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
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ParsingError(f"CVAT shape field '{field_name}' must be a non-negative integer.")
