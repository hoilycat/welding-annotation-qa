"""검증된 RIAWELC Polygon을 휴대 가능한 YOLO segmentation dataset으로 내보낸다."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
from typing import Any

import yaml

from .dataset_export import ValidatedDatasetImage, validate_export_dataset
from .models import DefectAnnotation, ParsingError, validate_image_dimensions
from .taxonomy import TaxonomyConfig


def _format_normalized_coordinate(value: float) -> str:
    """정규화 좌표를 불필요한 0 없이 충분한 정밀도의 안정된 문자열로 만든다."""
    # 12 significant digits면 일반적인 영상 좌표를 복원하기에 충분하면서 diff도 읽기 쉽다.
    return format(value, ".12g")


def annotation_to_yolo_segment(
    annotation: DefectAnnotation,
    class_ids: Mapping[str, int],
    *,
    width: int,
    height: int,
) -> str:
    """annotation 하나를 `class x1 y1 ...` YOLO segmentation 한 줄로 바꾼다."""
    if not isinstance(annotation, DefectAnnotation):
        raise ParsingError("YOLO segment conversion requires a DefectAnnotation instance.")
    if not isinstance(class_ids, Mapping):
        raise ParsingError("YOLO class IDs must be a mapping.")
    if annotation.label_canonical not in class_ids:
        raise ParsingError(
            f"No YOLO class ID configured for canonical label "
            f"'{annotation.label_canonical}'."
        )
    class_id = class_ids[annotation.label_canonical]
    if isinstance(class_id, bool) or not isinstance(class_id, int) or class_id < 0:
        raise ParsingError("YOLO class ID must be a non-negative integer.")

    normalized_width, normalized_height = validate_image_dimensions(
        width=width,
        height=height,
    )
    # 두 값을 모두 전달했으므로 validate_image_dimensions가 None을 반환할 수 없다.
    assert normalized_width is not None and normalized_height is not None

    # 공통 검증기가 실제 이미지 경계를 보증했으므로 여기서는 pixel을 0~1로만 정규화한다.
    coordinates = [
        normalized
        for x, y in zip(annotation.polygon.x, annotation.polygon.y)
        for normalized in (x / normalized_width, y / normalized_height)
    ]
    if any(value < 0.0 or value > 1.0 for value in coordinates):
        raise ParsingError("YOLO normalized polygon coordinates must be between 0 and 1.")

    return " ".join(
        [str(class_id)]
        + [_format_normalized_coordinate(value) for value in coordinates]
    )


def _build_label_text(
    image: ValidatedDatasetImage,
    class_ids: dict[str, int],
) -> str:
    """이미지 한 장의 모든 Polygon을 YOLO label 파일 본문으로 만든다."""
    lines = [
        annotation_to_yolo_segment(
            annotation,
            class_ids,
            width=image.width,
            height=image.height,
        )
        for annotation in image.annotations
    ]
    # 정상 이미지는 의도적인 빈 파일, 결함 이미지는 마지막 newline이 있는 text로 출력한다.
    return "" if not lines else "\n".join(lines) + "\n"


def _sha256_file(path: Path) -> str:
    """큰 이미지도 메모리에 전부 올리지 않고 SHA-256을 계산한다."""
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_yolo_dataset(
    image_root: str | Path,
    annotation_root: str | Path,
    taxonomy: TaxonomyConfig,
    *,
    modality: str = "RT",
    allow_missing_annotations: bool = False,
) -> dict[str, Any]:
    """전체 입력을 검증하고 YOLO 파일 생성에 필요한 결정적인 계획을 만든다."""
    dataset = validate_export_dataset(
        image_root,
        annotation_root,
        taxonomy,
        modality=modality,
        allow_missing_annotations=allow_missing_annotations,
    )
    # YOLO class ID는 0부터 시작하며 COCO와 동일한 taxonomy 순서를 사용한다.
    class_ids = {
        name: index for index, name in enumerate(dataset.category_names)
    }

    items: list[dict[str, Any]] = []
    for image in dataset.images:
        relative_image = PurePosixPath(image.relative_path)
        relative_label = relative_image.with_suffix(".txt")
        items.append(
            {
                # Path 객체는 writer 내부에서만 사용하고 manifest에는 상대 POSIX 경로를 기록한다.
                "source_path": image.path,
                "image_file": (PurePosixPath("images") / relative_image).as_posix(),
                "label_file": (PurePosixPath("labels") / relative_label).as_posix(),
                "width": image.width,
                "height": image.height,
                "annotations": len(image.annotations),
                "label_text": _build_label_text(image, class_ids),
            }
        )

    return {
        "format": "yolo-segmentation",
        "version": "1.0",
        "modality": dataset.modality,
        "names": {index: name for name, index in class_ids.items()},
        "items": items,
    }


def _write_yolo_dataset(dataset: dict[str, Any], output_dir: str | Path) -> Path:
    """검증된 생성 계획을 임시 폴더에 완성한 후 목적지로 원자적으로 이동한다."""
    destination = Path(output_dir)
    if destination.exists():
        raise ParsingError(
            f"YOLO output directory already exists: {destination}. "
            "Choose a new directory to avoid overwriting a dataset."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}-staging-",
            dir=destination.parent,
        )
    )
    try:
        manifest_items: list[dict[str, Any]] = []
        for item in dataset["items"]:
            image_output = staging / Path(item["image_file"])
            label_output = staging / Path(item["label_file"])
            image_output.parent.mkdir(parents=True, exist_ok=True)
            label_output.parent.mkdir(parents=True, exist_ok=True)

            # copy2는 원본을 건드리지 않으면서 timestamp 같은 기본 파일 메타데이터도 보존한다.
            shutil.copy2(item["source_path"], image_output)
            # 검증과 복사 사이 원본 변경이나 저장장치 오류를 감지해 잘못된 학습 사본을 차단한다.
            source_sha256 = _sha256_file(item["source_path"])
            copied_sha256 = _sha256_file(image_output)
            if copied_sha256 != source_sha256:
                raise ParsingError(
                    f"Copied image checksum does not match source: {item['source_path']}"
                )
            label_output.write_text(item["label_text"], encoding="utf-8", newline="\n")
            manifest_item = {
                key: item[key]
                for key in (
                    "image_file",
                    "label_file",
                    "width",
                    "height",
                    "annotations",
                )
            }
            manifest_item["sha256"] = copied_sha256
            manifest_items.append(manifest_item)

        # Ultralytics data.yaml에 옮겨 쓸 수 있는 0-based class 매핑을 별도 보존한다.
        (staging / "classes.yaml").write_text(
            yaml.safe_dump(
                {"names": dataset["names"]},
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
            newline="\n",
        )
        (staging / "manifest.json").write_text(
            json.dumps(
                {
                    "format": dataset["format"],
                    "version": dataset["version"],
                    "modality": dataset["modality"],
                    "names": dataset["names"],
                    "images": manifest_items,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

        # 검증 뒤 다른 process가 목적지를 만들었어도 빈 폴더까지 덮어쓰지 않게 다시 확인한다.
        if destination.exists():
            raise ParsingError(
                f"YOLO output directory was created during export: {destination}."
            )
        # 같은 filesystem 안의 rename으로 완성 전 dataset이 목적지에 노출되지 않게 한다.
        staging.replace(destination)
    except Exception:
        # staging은 이 함수가 방금 만든 경로이므로 실패한 임시 산출물만 제한적으로 정리한다.
        if staging.exists():
            shutil.rmtree(staging)
        raise

    return destination


def export_yolo_dataset(
    image_root: str | Path,
    annotation_root: str | Path,
    output_dir: str | Path,
    taxonomy: TaxonomyConfig,
    *,
    modality: str = "RT",
    allow_missing_annotations: bool = False,
) -> dict[str, Any]:
    """입력 검증, YOLO 계획 생성, 안전한 디렉터리 기록을 한 번에 수행한다."""
    dataset = build_yolo_dataset(
        image_root,
        annotation_root,
        taxonomy,
        modality=modality,
        allow_missing_annotations=allow_missing_annotations,
    )
    destination = _write_yolo_dataset(dataset, output_dir)
    return {
        "images": len(dataset["items"]),
        "annotations": sum(item["annotations"] for item in dataset["items"]),
        "classes": len(dataset["names"]),
        "output": str(destination),
    }


def _build_parser() -> argparse.ArgumentParser:
    """YOLO segmentation export CLI가 지원하는 명령행 인자를 구성한다."""
    parser = argparse.ArgumentParser(
        description="Export validated RIAWELC polygons as a YOLO segmentation dataset."
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
        help="Keep images without matching JSON as empty YOLO label files",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="New directory for copied images, labels, classes, and manifest",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """YOLO dataset을 생성하고 자동화가 읽을 수 있는 JSON 요약을 출력한다."""
    args = _build_parser().parse_args(argv)
    try:
        taxonomy = (
            TaxonomyConfig.load_from_yaml(args.taxonomy)
            if args.taxonomy
            else TaxonomyConfig.load_default()
        )
        result = export_yolo_dataset(
            args.images,
            args.annotations,
            args.output_dir,
            taxonomy,
            modality=args.modality,
            allow_missing_annotations=args.allow_missing_annotations,
        )
    except (ParsingError, FileNotFoundError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
