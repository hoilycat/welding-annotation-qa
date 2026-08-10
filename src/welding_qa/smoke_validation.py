"""CVAT smoke test export가 입력 annotation과 정확히 일치하는지 검증한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .cvat_task import collect_image_paths, load_annotations_for_images
from .models import DefectAnnotation, ParsingError
from .taxonomy import TaxonomyConfig


def _canonical_shapes(
    annotations: list[DefectAnnotation],
) -> list[tuple[str, tuple[float, ...], tuple[float, ...]]]:
    """순서와 원본 alias 표기에 무관한 canonical polygon 비교값을 만든다."""
    return sorted(
        (
            annotation.label_canonical,
            annotation.polygon.x,
            annotation.polygon.y,
        )
        for annotation in annotations
    )


def validate_smoke_export(
    image_root: str | Path,
    export_root: str | Path,
    taxonomy: TaxonomyConfig,
    *,
    modality: str,
    annotation_root: str | Path | None = None,
) -> dict[str, Any]:
    """이미지별 export 라벨과 좌표를 입력 annotation 또는 빈 기준과 대조한다."""
    image_paths = collect_image_paths(image_root)
    exported = load_annotations_for_images(
        export_root,
        image_paths,
        taxonomy,
        modality=modality,
    )
    expected = (
        load_annotations_for_images(
            annotation_root,
            image_paths,
            taxonomy,
            modality=modality,
        )
        if annotation_root is not None
        else {path.name: [] for path in image_paths}
    )

    mismatched_files = sorted(
        filename
        for filename in expected
        if _canonical_shapes(expected[filename])
        != _canonical_shapes(exported[filename])
    )
    if mismatched_files:
        raise ParsingError(
            "CVAT export labels or polygon coordinates do not match the input for: "
            + ", ".join(mismatched_files)
        )

    return {
        "images": len(image_paths),
        "annotations_expected": sum(len(items) for items in expected.values()),
        "annotations_exported": sum(len(items) for items in exported.values()),
        "round_trip_exact": True,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an exact CVAT canonical annotation smoke-test round trip."
    )
    parser.add_argument("--images", required=True, type=Path)
    parser.add_argument("--export-dir", required=True, type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--modality", default="RT")
    parser.add_argument(
        "--taxonomy",
        type=Path,
        help="Path to a custom taxonomy YAML (defaults to packaged canonical taxonomy)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        taxonomy = (
            TaxonomyConfig.load_from_yaml(args.taxonomy)
            if args.taxonomy
            else TaxonomyConfig.load_default()
        )
        result = validate_smoke_export(
            args.images,
            args.export_dir,
            taxonomy,
            modality=args.modality,
            annotation_root=args.annotations,
        )
    except (ParsingError, FileNotFoundError, OSError) as exc:
        print(f"error: {exc}")
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
