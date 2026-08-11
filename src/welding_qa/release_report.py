"""Dataset-level QA, release manifest와 정적 HTML 대시보드를 한 번에 생성한다."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from PIL import Image, ImageOps

from .dashboard import render_dashboard
from .dataset_qa import (
    find_annotation_issues,
    find_dataset_alignment_issues,
    find_duplicate_images,
    summarize_issue_codes,
)
from .models import ParsingError
from .qa_report import build_qa_report
from .taxonomy import TaxonomyConfig


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _annotation_inventory(annotation_root: str | Path) -> list[dict[str, str]]:
    root = Path(annotation_root)
    if not root.is_dir():
        raise ParsingError(f"Annotation root must be an existing directory: {root}")
    return [
        {
            "file": path.relative_to(root).as_posix(),
            "sha256": _sha256_file(path),
        }
        for path in sorted(
            (candidate for candidate in root.rglob("*.json") if candidate.is_file()),
            key=lambda candidate: candidate.relative_to(root).as_posix().lower(),
        )
    ]


def _dataset_digest(
    annotation_inventory: list[dict[str, str]],
    image_inventory: list[dict[str, str]],
) -> str:
    """파일 상대 경로와 checksum 전체를 하나의 재현 가능한 dataset 지문으로 묶는다."""
    digest = hashlib.sha256()
    entries = [
        ("annotation", item["file"], item["sha256"])
        for item in annotation_inventory
    ] + [
        ("image", item["file"], item["sha256"])
        for item in image_inventory
    ]
    for kind, relative_path, checksum in sorted(entries):
        digest.update(f"{kind}\0{relative_path}\0{checksum}\n".encode("utf-8"))
    return digest.hexdigest()


def _redact_local_paths(
    value: Any,
    *,
    image_root: str | Path,
    annotation_root: str | Path,
) -> Any:
    """공유 가능한 report에 로컬 절대·입력 경로가 남지 않게 재귀적으로 가린다."""
    replacements: list[tuple[str, str]] = []
    for root, placeholder in (
        (image_root, "<images>"),
        (annotation_root, "<annotations>"),
    ):
        path = Path(root)
        for candidate in {str(path), str(path.resolve()), path.as_posix()}:
            if candidate:
                replacements.append((candidate, placeholder))
    replacements.sort(key=lambda item: len(item[0]), reverse=True)

    if isinstance(value, str):
        result = value
        for source, replacement in replacements:
            result = result.replace(source, replacement)
        return result
    if isinstance(value, list):
        return [
            _redact_local_paths(
                item,
                image_root=image_root,
                annotation_root=annotation_root,
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _redact_local_paths(
                item,
                image_root=image_root,
                annotation_root=annotation_root,
            )
            for key, item in value.items()
        }
    return value


def build_release_manifest(
    image_root: str | Path,
    annotation_root: str | Path,
    taxonomy: TaxonomyConfig,
    *,
    modality: str | None = None,
    overlap_threshold: float = 0.10,
    duplicate_annotation_iou: float = 0.90,
    perceptual_distance: int = 8,
    brightness_tolerance: float = 24.0,
) -> dict[str, Any]:
    """기본 QA와 dataset-level 검사를 실행해 release manifest를 반환한다."""
    qa = build_qa_report(annotation_root, taxonomy, modality=modality)
    annotation_issues = find_annotation_issues(
        annotation_root,
        taxonomy,
        modality=modality,
        overlap_threshold=overlap_threshold,
        duplicate_iou_threshold=duplicate_annotation_iou,
    )
    duplicate_images = find_duplicate_images(
        image_root,
        perceptual_distance=perceptual_distance,
        brightness_tolerance=brightness_tolerance,
    )
    alignment_issues = find_dataset_alignment_issues(image_root, annotation_root)
    annotation_inventory = _annotation_inventory(annotation_root)
    image_inventory = duplicate_images.pop("inventory")
    duplicate_files = {
        file_name
        for pair in duplicate_images["pairs"]
        for file_name in pair["files"]
    }
    blocking_annotation_issues = [
        issue for issue in annotation_issues if issue.get("severity") == "error"
    ]
    review_items = len(annotation_issues) + len(duplicate_images["pairs"])
    blocking_errors = (
        qa["files_invalid"]
        + len(duplicate_images["errors"])
        + len(alignment_issues)
        + len(blocking_annotation_issues)
    )
    status = "failed" if blocking_errors else "review" if review_items else "passed"
    annotation_issue_counts = summarize_issue_codes(annotation_issues)
    status_reasons: list[dict[str, Any]] = []
    if qa["files_invalid"]:
        status_reasons.append(
            {
                "code": "invalid_annotation_files",
                "count": qa["files_invalid"],
                "message": "파싱 또는 taxonomy 검증을 통과하지 못한 JSON이 있습니다.",
            }
        )
    if alignment_issues:
        status_reasons.append(
            {
                "code": "dataset_alignment_errors",
                "count": len(alignment_issues),
                "message": "이미지와 annotation JSON의 일대일 대응을 확인해야 합니다.",
            }
        )
    if duplicate_images["errors"]:
        status_reasons.append(
            {
                "code": "unreadable_images",
                "count": len(duplicate_images["errors"]),
                "message": "읽거나 hash를 계산할 수 없는 이미지가 있습니다.",
            }
        )
    if blocking_annotation_issues:
        status_reasons.append(
            {
                "code": "annotation_blocking_errors",
                "count": len(blocking_annotation_issues),
                "message": "서로 다른 canonical label이 겹치는 annotation 오류가 있습니다.",
            }
        )
    review_annotation_issues = [
        issue for issue in annotation_issues if issue.get("severity") != "error"
    ]
    if review_annotation_issues:
        status_reasons.append(
            {
                "code": "annotation_review_candidates",
                "count": len(review_annotation_issues),
                "message": "IoU 기준을 넘은 annotation 중첩·중복 후보가 있습니다.",
            }
        )
    if duplicate_images["pairs"]:
        status_reasons.append(
            {
                "code": "similar_image_pairs",
                "count": len(duplicate_images["pairs"]),
                "message": (
                    f"Perceptual hash 거리 {perceptual_distance} 이하, 밝기 차이 "
                    f"{brightness_tolerance:g} 이하인 이미지 쌍이 있습니다."
                ),
            }
        )
    if not status_reasons:
        status_reasons.append(
            {
                "code": "all_checks_clear",
                "count": 0,
                "message": "파싱, 대응, Polygon 겹침과 이미지 중복 검사에서 검토 후보가 없습니다.",
            }
        )

    normalized_modality = modality.strip().upper() if isinstance(modality, str) else None
    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "status_reasons": status_reasons,
        "modality": normalized_modality,
        "dataset_digest": _dataset_digest(annotation_inventory, image_inventory),
        "sources": {
            "image_root": "<images>",
            "annotation_root": "<annotations>",
            "paths_redacted": True,
        },
        "taxonomy": {
            "version": taxonomy.raw_config.get("version"),
            "canonical_labels": list(taxonomy.canonical_classes),
        },
        "thresholds": {
            "overlap_ratio": overlap_threshold,
            "duplicate_annotation_iou": duplicate_annotation_iou,
            "perceptual_hash_distance": perceptual_distance,
            "brightness_tolerance": brightness_tolerance,
        },
        "summary": {
            "images": duplicate_images["images_scanned"],
            "valid_files": qa["files_valid"],
            "invalid_files": qa["files_invalid"],
            "annotations": qa["annotation_count"],
            "review_items": review_items,
            "duplicate_images": len(duplicate_files),
            "duplicate_pairs": len(duplicate_images["pairs"]),
            "blocking_errors": blocking_errors,
        },
        "qa": qa,
        "checks": {
            "alignment_issues": alignment_issues,
            "annotation_issue_counts": annotation_issue_counts,
            "annotation_issues": annotation_issues,
            "duplicate_images": duplicate_images,
        },
        "inventory": {
            "annotations": annotation_inventory,
            "images": image_inventory,
        },
        "artifacts": {
            "qa_report": "qa-report.json",
            "manifest": "release-manifest.json",
            "dashboard": "dashboard.html",
        },
    }
    return _redact_local_paths(
        manifest,
        image_root=image_root,
        annotation_root=annotation_root,
    )


def _attach_duplicate_thumbnails(
    manifest: dict[str, Any],
    staging: Path,
    image_root: str | Path,
) -> None:
    """중복 후보의 작은 JPEG만 report에 복사하고 pair에 상대 경로를 연결한다."""
    pairs = manifest["checks"]["duplicate_images"]["pairs"]
    unique_files = sorted({file_name for pair in pairs for file_name in pair["files"]})
    if not unique_files:
        return

    root = Path(image_root).resolve()
    thumbnail_dir = staging / "thumbnails"
    thumbnail_dir.mkdir()
    thumbnail_paths: dict[str, str] = {}
    for index, relative_name in enumerate(unique_files, start=1):
        source = (root / Path(relative_name)).resolve()
        if source != root and root not in source.parents:
            raise ParsingError(f"Duplicate image path escapes image root: {relative_name}")
        try:
            with Image.open(source) as image:
                preview = ImageOps.exif_transpose(image).convert("RGB")
                preview.thumbnail((640, 360), Image.Resampling.LANCZOS)
                output_name = f"candidate-{index:03d}.jpg"
                preview.save(thumbnail_dir / output_name, format="JPEG", quality=86)
        except OSError as exc:
            raise ParsingError(
                f"Could not create thumbnail for '{relative_name}': {exc}"
            ) from exc
        thumbnail_paths[relative_name] = f"thumbnails/{output_name}"

    for pair in pairs:
        pair["thumbnails"] = [thumbnail_paths[file_name] for file_name in pair["files"]]
    manifest["artifacts"]["thumbnails"] = "thumbnails/"


def write_release_bundle(
    manifest: dict[str, Any],
    output_dir: str | Path,
    *,
    image_root: str | Path | None = None,
) -> Path:
    """세 산출물을 staging에서 완성한 뒤 새 출력 폴더로 한 번에 이동한다."""
    destination = Path(output_dir)
    if destination.exists():
        raise ParsingError(
            f"Release output directory already exists: {destination}. "
            "Choose a new directory to avoid overwriting a report."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}-staging-",
            dir=destination.parent,
        )
    )
    try:
        if image_root is not None:
            _attach_duplicate_thumbnails(manifest, staging, image_root)
        (staging / "qa-report.json").write_text(
            json.dumps(manifest["qa"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (staging / "release-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (staging / "dashboard.html").write_text(
            render_dashboard(manifest),
            encoding="utf-8",
            newline="\n",
        )
        if destination.exists():
            raise ParsingError(f"Release output directory was created during export: {destination}")
        staging.replace(destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return destination


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build dataset QA, a release manifest, and a static HTML dashboard."
    )
    parser.add_argument("--images", required=True, type=Path, help="Image directory")
    parser.add_argument(
        "--annotations",
        required=True,
        type=Path,
        help="RIAWELC JSON annotation directory",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--modality", help="Require every JSON file to use this modality")
    parser.add_argument(
        "--taxonomy",
        type=Path,
        help="Path to a custom taxonomy YAML (defaults to packaged canonical taxonomy)",
    )
    parser.add_argument("--overlap-threshold", type=float, default=0.10)
    parser.add_argument("--duplicate-annotation-iou", type=float, default=0.90)
    parser.add_argument("--perceptual-distance", type=int, default=8)
    parser.add_argument("--brightness-tolerance", type=float, default=24.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        taxonomy = (
            TaxonomyConfig.load_from_yaml(args.taxonomy)
            if args.taxonomy
            else TaxonomyConfig.load_default()
        )
        manifest = build_release_manifest(
            args.images,
            args.annotations,
            taxonomy,
            modality=args.modality,
            overlap_threshold=args.overlap_threshold,
            duplicate_annotation_iou=args.duplicate_annotation_iou,
            perceptual_distance=args.perceptual_distance,
            brightness_tolerance=args.brightness_tolerance,
        )
        output = write_release_bundle(
            manifest,
            args.output_dir,
            image_root=args.images,
        )
    except (ParsingError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": manifest["status"],
                "review_items": manifest["summary"]["review_items"],
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 1 if manifest["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
