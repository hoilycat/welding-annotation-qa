from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import DefectAnnotation, ParsingError, Polygon
from .taxonomy import TaxonomyConfig


def parse_riawelc_json(
    json_path_or_content: str | Path | dict[str, Any],
    taxonomy: TaxonomyConfig,
    default_modality: str = "RT",
) -> list[DefectAnnotation]:
    """Parse RIAWELC format JSON annotation and return validated DefectAnnotation instances."""
    if isinstance(json_path_or_content, (str, Path)) and (
        isinstance(json_path_or_content, Path) or Path(json_path_or_content).is_file()
    ):
        path = Path(json_path_or_content)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ParsingError(f"Invalid JSON in file '{path}': {exc.msg}") from exc
    elif isinstance(json_path_or_content, str):
        try:
            data = json.loads(json_path_or_content)
        except json.JSONDecodeError as exc:
            raise ParsingError(f"Invalid JSON content: {exc.msg}") from exc
    elif isinstance(json_path_or_content, dict):
        data = json_path_or_content
    else:
        raise ParsingError(f"Invalid JSON input type: {type(json_path_or_content)}")

    if not isinstance(data, dict):
        raise ParsingError("Root JSON structure must be a dictionary object.")

    annotations_field = None
    for candidate in ("annotations", "shapes", "objects"):
        if candidate in data:
            annotations_field = candidate
            break
    if annotations_field is None:
        raise ParsingError("JSON missing required 'annotations', 'shapes', or 'objects' list field.")
    annotations_list = data[annotations_field]
    if not isinstance(annotations_list, list):
        raise ParsingError(f"Field '{annotations_field}' must be a list.")

    modality = data.get("modality") or default_modality
    if not isinstance(modality, str):
        raise ParsingError("Field 'modality' must be a string.")
    image_info = data.get("image_info")
    if not isinstance(image_info, dict):
        image_info = {}

    parsed_defects: list[DefectAnnotation] = []

    for idx, item in enumerate(annotations_list):
        if not isinstance(item, dict):
            raise ParsingError(f"Annotation item at index {idx} must be a dictionary object.")

        raw_label = item.get("label") or item.get("class_name") or item.get("defect_type")
        if not raw_label:
            raise ParsingError(f"Annotation item at index {idx} missing label field.")

        try:
            canonical_slug = taxonomy.get_canonical_slug(str(raw_label))
        except ValueError as exc:
            raise ParsingError(
                f"Annotation item at index {idx} has invalid label: {exc}"
            ) from exc
        if not taxonomy.is_modality_allowed(canonical_slug, modality):
            raise ParsingError(
                f"Annotation item at index {idx}: modality '{modality}' is not allowed "
                f"for canonical label '{canonical_slug}'."
            )

        if "polygon" in item:
            poly_data = item["polygon"]
        elif "points" in item:
            poly_data = item["points"]
        else:
            poly_data = item

        if isinstance(poly_data, dict):
            xs = poly_data.get("x") if "x" in poly_data else poly_data.get("xs")
            ys = poly_data.get("y") if "y" in poly_data else poly_data.get("ys")
        elif isinstance(poly_data, (list, tuple)):
            xs = []
            ys = []
            for point_idx, point in enumerate(poly_data):
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    raise ParsingError(
                        f"Annotation item at index {idx}, point at index {point_idx} "
                        "must be a list or tuple containing exactly 2 coordinates."
                    )
                xs.append(point[0])
                ys.append(point[1])
        else:
            xs, ys = None, None

        if xs is None or ys is None:
            raise ParsingError(f"Annotation item at index {idx} missing 'x' and 'y' polygon coordinates.")

        if not isinstance(xs, (list, tuple)) or not isinstance(ys, (list, tuple)):
            raise ParsingError(
                f"Annotation item at index {idx} polygon fields 'x' and 'y' must be lists or tuples."
            )

        if len(xs) != len(ys):
            raise ParsingError(
                f"Annotation item at index {idx}: x and y coordinate lengths mismatch: "
                f"len(x)={len(xs)}, len(y)={len(ys)}"
            )

        try:
            polygon = Polygon(x=tuple(xs), y=tuple(ys))
        except ParsingError as exc:
            raise ParsingError(f"Annotation item at index {idx}: {exc}") from exc

        parsed_defects.append(
            DefectAnnotation(
                label_original=str(raw_label),
                label_canonical=canonical_slug,
                polygon=polygon,
                modality=modality,
                extra_meta={
                    "image_id": image_info.get("image_id", data.get("image_id")),
                    "filename": image_info.get("filename", data.get("filename")),
                    "width": image_info.get("width", data.get("width")),
                    "height": image_info.get("height", data.get("height")),
                },
            )
        )

    return parsed_defects
