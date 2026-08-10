"""검증된 RIAWELC Polygon annotation을 COCO instance segmentation JSON으로 내보낸다."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

from PIL import Image, UnidentifiedImageError

from .cvat_task import collect_image_paths, load_annotations_for_images
from .models import DefectAnnotation, ParsingError, Polygon
from .taxonomy import TaxonomyConfig


def _read_image_size(path: Path) -> tuple[int, int]:
    """실제 이미지 파일을 검증하고 COCO에 기록할 pixel 크기를 읽는다."""
    try:
        with Image.open(path) as image:
            width, height = image.size
            # size header만 읽고 성공하는 손상 파일을 막기 위해 전체 구조도 검증한다.
            image.verify()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ParsingError(f"Could not read image '{path}': {exc}") from exc

    if width <= 0 or height <= 0:
        raise ParsingError(f"Image '{path}' must have positive width and height.")
    return width, height


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


def _validate_annotation_image_metadata(
    annotation: DefectAnnotation,
    image_path: Path,
    width: int,
    height: int,
) -> None:
    """JSON 이미지 메타데이터가 실제 매칭된 파일과 모순되지 않는지 확인한다."""
    metadata = annotation.extra_meta
    metadata_filename = metadata.get("filename")
    if metadata_filename:
        # 다른 OS에서 기록한 경로도 basename 비교가 되도록 두 separator를 통일한다.
        normalized_name = str(metadata_filename).replace("\\", "/").rsplit("/", 1)[-1]
        if normalized_name.casefold() != image_path.name.casefold():
            raise ParsingError(
                f"Annotation image filename '{metadata_filename}' does not match "
                f"actual image '{image_path.name}'."
            )

    for field_name, metadata_value, actual_value in (
        ("width", metadata.get("width"), width),
        ("height", metadata.get("height"), height),
    ):
        if metadata_value is not None and float(metadata_value) != float(actual_value):
            raise ParsingError(
                f"Annotation image {field_name} {metadata_value} does not match "
                f"actual image {field_name} {actual_value} for '{image_path.name}'."
            )

    # JSON에 크기가 없더라도 실제 이미지 기준으로 Polygon 경계를 다시 검사한다.
    annotation.polygon.validate_image_bounds(width=width, height=height)


def build_coco_dataset(
    image_root: str | Path,
    annotation_root: str | Path,
    taxonomy: TaxonomyConfig,
    *,
    modality: str = "RT",
    allow_missing_annotations: bool = False,
) -> dict[str, Any]:
    """이미지와 RIAWELC JSON 폴더를 검증해 결정적인 COCO dataset을 만든다."""
    root = Path(image_root)
    image_paths = collect_image_paths(root)
    annotations_by_image = load_annotations_for_images(
        annotation_root,
        image_paths,
        taxonomy,
        modality=modality,
        allow_missing=allow_missing_annotations,
    )

    normalized_modality = modality.strip().upper()
    category_names = [
        slug
        for slug in taxonomy.canonical_classes
        if taxonomy.is_modality_allowed(slug, normalized_modality)
    ]
    if not category_names:
        raise ParsingError(
            f"No COCO categories are configured for modality '{normalized_modality}'."
        )
    category_ids = {name: index for index, name in enumerate(category_names, start=1)}

    coco_images: list[dict[str, Any]] = []
    coco_annotations: list[dict[str, Any]] = []
    annotation_id = 1
    resolved_root = root.resolve()

    for image_id, image_path in enumerate(image_paths, start=1):
        width, height = _read_image_size(image_path)
        coco_images.append(
            {
                "id": image_id,
                "file_name": image_path.relative_to(resolved_root).as_posix(),
                "width": width,
                "height": height,
            }
        )

        for annotation in annotations_by_image[image_path.name]:
            try:
                _validate_annotation_image_metadata(
                    annotation,
                    image_path,
                    width,
                    height,
                )
            except (ParsingError, TypeError, ValueError) as exc:
                raise ParsingError(f"Image '{image_path.name}': {exc}") from exc

            if annotation.label_canonical not in category_ids:
                raise ParsingError(
                    f"Image '{image_path.name}' has no COCO category for canonical label "
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
