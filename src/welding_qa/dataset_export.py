"""COCO와 YOLO exporter가 공유하는 실제 이미지·annotation 검증 경계."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .cvat_task import collect_image_paths, load_annotations_for_images
from .models import DefectAnnotation, ParsingError
from .taxonomy import TaxonomyConfig


@dataclass(frozen=True)
class ValidatedDatasetImage:
    """실제 파일 검사와 annotation 교차 검증을 통과한 이미지 한 장."""

    path: Path
    relative_path: str
    width: int
    height: int
    annotations: tuple[DefectAnnotation, ...]


@dataclass(frozen=True)
class ValidatedDataset:
    """export 형식과 무관하게 동일한 판정을 보장하는 검증 완료 dataset."""

    modality: str
    category_names: tuple[str, ...]
    images: tuple[ValidatedDatasetImage, ...]


def _read_image_size(path: Path) -> tuple[int, int]:
    """실제 이미지 전체 구조를 검증하고 pixel 크기를 읽는다."""
    try:
        with Image.open(path) as image:
            width, height = image.size
            # Header만 정상인 잘린 파일이 export되는 일을 막기 위해 본문 구조도 검사한다.
            image.verify()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ParsingError(f"Could not read image '{path}': {exc}") from exc

    if width <= 0 or height <= 0:
        raise ParsingError(f"Image '{path}' must have positive width and height.")
    return width, height


def _validate_annotation_image_metadata(
    annotation: DefectAnnotation,
    image_path: Path,
    width: int,
    height: int,
) -> None:
    """JSON의 파일 정보와 Polygon이 실제 이미지와 모순되지 않는지 확인한다."""
    metadata = annotation.extra_meta
    metadata_filename = metadata.get("filename")
    if metadata_filename:
        # Windows에서 기록한 backslash 경로도 macOS/Linux에서 basename 비교가 가능해야 한다.
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

    # JSON에 크기가 생략된 경우에도 실제 pixel 크기로 좌표 범위를 최종 보증한다.
    annotation.polygon.validate_image_bounds(width=width, height=height)


def validate_export_dataset(
    image_root: str | Path,
    annotation_root: str | Path,
    taxonomy: TaxonomyConfig,
    *,
    modality: str = "RT",
    allow_missing_annotations: bool = False,
) -> ValidatedDataset:
    """폴더 전체를 검증해 COCO와 YOLO가 공유할 불변 입력을 만든다."""
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
    category_names = tuple(
        slug
        for slug in taxonomy.canonical_classes
        if taxonomy.is_modality_allowed(slug, normalized_modality)
    )
    if not category_names:
        raise ParsingError(
            f"No export categories are configured for modality '{normalized_modality}'."
        )

    resolved_root = root.resolve()
    validated_images: list[ValidatedDatasetImage] = []
    for image_path in image_paths:
        width, height = _read_image_size(image_path)
        annotations = tuple(annotations_by_image[image_path.name])
        for annotation in annotations:
            try:
                _validate_annotation_image_metadata(
                    annotation,
                    image_path,
                    width,
                    height,
                )
            except (ParsingError, TypeError, ValueError) as exc:
                raise ParsingError(f"Image '{image_path.name}': {exc}") from exc

        # 상대 경로는 OS와 무관한 slash로 고정해 두 exporter의 ID·파일 순서를 일치시킨다.
        validated_images.append(
            ValidatedDatasetImage(
                path=image_path,
                relative_path=image_path.relative_to(resolved_root).as_posix(),
                width=width,
                height=height,
                annotations=annotations,
            )
        )

    return ValidatedDataset(
        modality=normalized_modality,
        category_names=category_names,
        images=tuple(validated_images),
    )
