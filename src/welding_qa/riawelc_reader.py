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

    annotations_list = data.get("annotations") or data.get("shapes") or data.get("objects")
    if annotations_list is None:
        raise ParsingError("JSON missing required 'annotations', 'shapes', or 'objects' list field.")

    modality = data.get("modality") or default_modality

    parsed_defects: list[DefectAnnotation] = []

    for idx, item in enumerate(annotations_list):
        if not isinstance(item, dict):
            continue

        raw_label = item.get("label") or item.get("class_name") or item.get("defect_type")
        if not raw_label:
            raise ParsingError(f"Annotation item at index {idx} missing label field.")

        canonical_slug = taxonomy.get_canonical_slug(str(raw_label))

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
                extra_meta={"image_id": data.get("image_id"), "filename": data.get("filename")},
            )
        )

    return parsed_defects
