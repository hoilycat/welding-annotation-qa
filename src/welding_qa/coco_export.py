"""검증된 RIAWELC Polygon annotation을 COCO instance segmentation JSON으로 내보낸다."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

from .dataset_export import validate_export_dataset
from .models import ParsingError, Polygon
from .taxonomy import TaxonomyConfig


def _polygon_area(polygon: Polygon) -> float:
    """Shoelace 공식으로 COCO annotation에 기록할 Polygon 면적을 계산한다."""
    points = tuple(zip(polygon.x, polygon.y))
    return abs(
        math.fsum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
        )
    ) / 2.0


def _polygon_bbox(polygon: Polygon) -> list[float]:
    """COCO의 [x, y, width, height] 형식 bounding box를 계산한다."""
    min_x, max_x = min(polygon.x), max(polygon.x)
    min_y, max_y = min(polygon.y), max(polygon.y)
    return [min_x, min_y, max_x - min_x, max_y - min_y]


def build_coco_dataset(
    image_root: str | Path,
    annotation_root: str | Path,
    taxonomy: TaxonomyConfig,
    *,
    modality: str = "RT",
    allow_missing_annotations: bool = False,
) -> dict[str, Any]:
    """이미지와 RIAWELC JSON 폴더를 검증해 결정적인 COCO dataset을 만든다."""
    dataset = validate_export_dataset(
        image_root,
        annotation_root,
        taxonomy,
        modality=modality,
        allow_missing_annotations=allow_missing_annotations,
    )
    category_names = dataset.category_names
    category_ids = {name: index for index, name in enumerate(category_names, start=1)}

    coco_images: list[dict[str, Any]] = []
    coco_annotations: list[dict[str, Any]] = []
    annotation_id = 1

    for image_id, image in enumerate(dataset.images, start=1):
        coco_images.append(
            {
                "id": image_id,
                "file_name": image.relative_path,
                "width": image.width,
                "height": image.height,
            }
        )

        for annotation in image.annotations:
            if annotation.label_canonical not in category_ids:
                raise ParsingError(
                    f"Image '{image.path.name}' has no COCO category for canonical label "
                    f"'{annotation.label_canonical}'."
                )

            segmentation = [
                coordinate
                for point in zip(annotation.polygon.x, annotation.polygon.y)
                for coordinate in point
            ]
            coco_annotations.append(
                {
                    "id": annotation_id,
                    "image_id": image_id,
                    "category_id": category_ids[annotation.label_canonical],
                    "segmentation": [segmentation],
                    "area": _polygon_area(annotation.polygon),
                    "bbox": _polygon_bbox(annotation.polygon),
                    "iscrowd": 0,
                }
            )
            annotation_id += 1

    return {
        "info": {
            "description": "Canonical welding defect polygon dataset",
            "version": "1.0",
        },
        "licenses": [],
        "images": coco_images,
        "annotations": coco_annotations,
        "categories": [
            {
                "id": category_ids[name],
                "name": name,
                "supercategory": "welding_defect",
            }
            for name in category_names
        ],
    }


def _build_parser() -> argparse.ArgumentParser:
    """COCO Polygon export CLI의 명령행 인자를 구성한다."""
    parser = argparse.ArgumentParser(
        description="Export validated RIAWELC polygons as COCO instance segmentation JSON."
    )
    parser.add_argument("--images", required=True, type=Path, help="Image directory")
    parser.add_argument(
        "--annotations",
        required=True,
        type=Path,
        help="RIAWELC JSON annotation directory",
    )
    parser.add_argument("--modality", default="RT", help="Dataset modality (default: RT)")
    parser.add_argument(
        "--taxonomy",
        type=Path,
        help="Path to a custom taxonomy YAML (defaults to packaged canonical taxonomy)",
    )
    parser.add_argument(
        "--allow-missing-annotations",
        action="store_true",
        help="Keep images without matching JSON as empty COCO images",
    )
    parser.add_argument("--output", required=True, type=Path, help="Output COCO JSON file")
    return parser


def main(argv: list[str] | None = None) -> int:
    """입력을 전부 검증한 뒤 COCO JSON과 자동화용 요약을 기록한다."""
    args = _build_parser().parse_args(argv)
    try:
        taxonomy = (
            TaxonomyConfig.load_from_yaml(args.taxonomy)
            if args.taxonomy
            else TaxonomyConfig.load_default()
        )
        dataset = build_coco_dataset(
            args.images,
            args.annotations,
            taxonomy,
            modality=args.modality,
            allow_missing_annotations=args.allow_missing_annotations,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (ParsingError, FileNotFoundError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "images": len(dataset["images"]),
                "annotations": len(dataset["annotations"]),
                "categories": len(dataset["categories"]),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
