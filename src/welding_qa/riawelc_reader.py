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
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    elif isinstance(json_path_or_content, str):
        data = json.loads(json_path_or_content)
    elif isinstance(json_path_or_content, dict):
        data = json_path_or_content
    else:
        raise ParsingError(f"Invalid JSON input type: {type(json_path_or_content)}")

    if not isinstance(data, dict):
        raise ParsingError("Root JSON structure must be a dictionary object.")

    annotations_list = None
    for field_name in ("annotations", "shapes", "objects"):
        if field_name in data:
            annotations_list = data[field_name]
            break
    if annotations_list is None:
        raise ParsingError("JSON missing required 'annotations', 'shapes', or 'objects' list field.")

    modality = data.get("modality") or default_modality
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

        canonical_slug = taxonomy.get_canonical_slug(str(raw_label))
        if not taxonomy.is_modality_allowed(canonical_slug, modality):
            raise ParsingError(
                f"Modality '{modality}' is not allowed for canonical label '{canonical_slug}'."
            )

        poly_data = item.get("polygon") or item.get("points") or item
        if isinstance(poly_data, dict):
            xs = poly_data.get("x") or poly_data.get("xs")
            ys = poly_data.get("y") or poly_data.get("ys")
        elif isinstance(poly_data, list):
            xs = [pt[0] for pt in poly_data if len(pt) >= 2]
            ys = [pt[1] for pt in poly_data if len(pt) >= 2]
        else:
            xs, ys = None, None

        if xs is None or ys is None:
            raise ParsingError(f"Annotation item at index {idx} missing 'x' and 'y' polygon coordinates.")

        if len(xs) != len(ys):
            raise ParsingError(
                f"x and y coordinate lengths mismatch: len(x)={len(xs)}, len(y)={len(ys)}"
            )

        polygon = Polygon(x=tuple(float(v) for v in xs), y=tuple(float(v) for v in ys))

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
