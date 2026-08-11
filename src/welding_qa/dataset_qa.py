"""여러 annotation과 이미지를 함께 비교하는 dataset-level QA 검사."""

from __future__ import annotations

from collections import Counter
import hashlib
import math
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageChops, ImageDraw, UnidentifiedImageError

from .cvat_task import collect_image_paths
from .models import ParsingError, Polygon
from .riawelc_reader import parse_riawelc_json
from .taxonomy import TaxonomyConfig


_MAX_MASK_SIDE = 2048
_MAX_MASK_PIXELS = 4_000_000


class _HashSearchNode:
    """Hamming 거리 기반 근접 hash 검색을 위한 작은 BK-tree node."""

    def __init__(self, value: int, index: int) -> None:
        self.value = value
        self.indices = [index]
        self.children: dict[int, _HashSearchNode] = {}

    def insert(self, value: int, index: int) -> None:
        distance = (self.value ^ value).bit_count()
        if distance == 0:
            self.indices.append(index)
            return
        child = self.children.get(distance)
        if child is None:
            self.children[distance] = _HashSearchNode(value, index)
        else:
            child.insert(value, index)

    def search(self, value: int, radius: int) -> list[int]:
        distance = (self.value ^ value).bit_count()
        matches = list(self.indices) if distance <= radius else []
        lower = distance - radius
        upper = distance + radius
        for edge, child in self.children.items():
            if lower <= edge <= upper:
                matches.extend(child.search(value, radius))
        return matches


def _polygon_bounds(polygon: Polygon) -> tuple[float, float, float, float]:
    """Polygon의 축 정렬 경계를 반환한다."""
    return min(polygon.x), min(polygon.y), max(polygon.x), max(polygon.y)


def _bounds_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    """두 bounding box가 양의 면적으로 겹칠 가능성이 있는지 빠르게 확인한다."""
    return (
        min(first[2], second[2]) > max(first[0], second[0])
        and min(first[3], second[3]) > max(first[1], second[1])
    )


def _raster_overlap_metrics(first: Polygon, second: Polygon) -> dict[str, float]:
    """Pillow 마스크를 이용해 임의 Polygon 두 개의 겹침 비율을 계산한다."""
    first_bounds = _polygon_bounds(first)
    second_bounds = _polygon_bounds(second)
    if not _bounds_overlap(first_bounds, second_bounds):
        return {"intersection_pixels": 0.0, "iou": 0.0, "smaller_overlap_ratio": 0.0}

    left = min(first_bounds[0], second_bounds[0])
    top = min(first_bounds[1], second_bounds[1])
    right = max(first_bounds[2], second_bounds[2])
    bottom = max(first_bounds[3], second_bounds[3])
    source_width = max(right - left, 1.0)
    source_height = max(bottom - top, 1.0)
    scale = min(
        1.0,
        _MAX_MASK_SIDE / source_width,
        _MAX_MASK_SIDE / source_height,
        math.sqrt(_MAX_MASK_PIXELS / (source_width * source_height)),
    )
    width = max(2, math.ceil(source_width * scale) + 3)
    height = max(2, math.ceil(source_height * scale) + 3)

    def make_mask(polygon: Polygon) -> Image.Image:
        mask = Image.new("1", (width, height), 0)
        points = [
            ((x - left) * scale + 1, (y - top) * scale + 1)
            for x, y in zip(polygon.x, polygon.y)
        ]
        ImageDraw.Draw(mask).polygon(points, fill=1)
        return mask

    first_mask = make_mask(first)
    second_mask = make_mask(second)
    intersection_mask = ImageChops.logical_and(first_mask, second_mask)
    first_area = float(sum(first_mask.histogram()[1:]))
    second_area = float(sum(second_mask.histogram()[1:]))
    intersection = float(sum(intersection_mask.histogram()[1:]))
    union = first_area + second_area - intersection
    smaller = min(first_area, second_area)
    return {
        "intersection_pixels": intersection,
        "iou": intersection / union if union else 0.0,
        "smaller_overlap_ratio": intersection / smaller if smaller else 0.0,
    }


def find_annotation_issues(
    annotation_root: str | Path,
    taxonomy: TaxonomyConfig,
    *,
    modality: str | None = None,
    overlap_threshold: float = 0.10,
    duplicate_iou_threshold: float = 0.90,
) -> list[dict[str, Any]]:
    """파일별 polygon 쌍을 비교해 라벨 충돌과 중복 후보를 반환한다."""
    if not 0.0 <= overlap_threshold <= 1.0:
        raise ParsingError("Overlap threshold must be between 0 and 1.")
    if not 0.0 <= duplicate_iou_threshold <= 1.0:
        raise ParsingError("Duplicate annotation IoU threshold must be between 0 and 1.")

    root = Path(annotation_root)
    if not root.is_dir():
        raise ParsingError(f"Annotation root must be an existing directory: {root}")

    files = sorted(
        (path for path in root.rglob("*.json") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix().lower(),
    )
    issues: list[dict[str, Any]] = []
    for path in files:
        try:
            annotations = parse_riawelc_json(
                path,
                taxonomy,
                expected_modality=modality,
            )
        except (ParsingError, OSError, UnicodeError):
            # 기본 QA 리포트가 파싱 오류를 자세히 기록하므로 여기서는 유효 파일만 비교한다.
            continue

        for first_index, first in enumerate(annotations):
            for second_index in range(first_index + 1, len(annotations)):
                second = annotations[second_index]
                metrics = _raster_overlap_metrics(first.polygon, second.polygon)
                iou = metrics["iou"]
                smaller_overlap = metrics["smaller_overlap_ratio"]
                if metrics["intersection_pixels"] == 0:
                    continue

                if first.label_canonical != second.label_canonical:
                    if smaller_overlap < overlap_threshold:
                        continue
                    code = "label_conflict"
                    severity = "error"
                elif iou >= duplicate_iou_threshold:
                    code = "possible_duplicate_annotation"
                    severity = "warning"
                elif iou >= overlap_threshold:
                    code = "annotation_overlap"
                    severity = "warning"
                else:
                    continue

                issues.append(
                    {
                        "code": code,
                        "severity": severity,
                        "file": path.relative_to(root).as_posix(),
                        "annotation_indices": [first_index, second_index],
                        "labels": [first.label_canonical, second.label_canonical],
                        "iou": round(iou, 6),
                        "smaller_overlap_ratio": round(smaller_overlap, 6),
                    }
                )
    return issues


def _sha256_file(path: Path) -> str:
    """대용량 이미지도 한 번에 메모리에 올리지 않고 SHA-256을 계산한다."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _perceptual_hash(path: Path) -> tuple[int, float]:
    """64비트 dHash와 64비트 평균 hash를 합친 128비트 지문을 만든다."""
    try:
        with Image.open(path) as source:
            image = source.convert("L")
            difference_image = image.resize((9, 8), Image.Resampling.LANCZOS)
            average_image = image.resize((8, 8), Image.Resampling.LANCZOS)
            difference_pixels = _image_pixels(difference_image)
            average_pixels = _image_pixels(average_image)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ParsingError(f"Could not read image '{path}': {exc}") from exc

    difference_bits = 0
    for row in range(8):
        for column in range(8):
            difference_bits = (difference_bits << 1) | int(
                difference_pixels[row * 9 + column]
                < difference_pixels[row * 9 + column + 1]
            )

    mean_brightness = sum(average_pixels) / len(average_pixels)
    average_bits = 0
    for pixel in average_pixels:
        average_bits = (average_bits << 1) | int(pixel >= mean_brightness)
    return (difference_bits << 64) | average_bits, mean_brightness


def _image_pixels(image: Image.Image) -> list[int]:
    """Pillow 10부터 최신 버전까지 폐기 경고 없이 단일 채널 픽셀을 읽는다."""
    flattened = getattr(image, "get_flattened_data", None)
    if flattened is not None:
        return list(flattened())
    return list(image.getdata())


def find_duplicate_images(
    image_root: str | Path,
    *,
    perceptual_distance: int = 8,
    brightness_tolerance: float = 24.0,
) -> dict[str, Any]:
    """완전 동일 이미지와 시각적으로 유사한 이미지 쌍을 찾는다."""
    if (
        isinstance(perceptual_distance, bool)
        or not isinstance(perceptual_distance, int)
        or not 0 <= perceptual_distance <= 128
    ):
        raise ParsingError("Perceptual distance must be an integer between 0 and 128.")
    if not 0.0 <= brightness_tolerance <= 255.0:
        raise ParsingError("Brightness tolerance must be between 0 and 255.")

    root = Path(image_root)
    paths = collect_image_paths(root)
    fingerprints: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in paths:
        relative_path = path.relative_to(root.resolve()).as_posix()
        try:
            visual_hash, brightness = _perceptual_hash(path)
            fingerprints.append(
                {
                    "file": relative_path,
                    "sha256": _sha256_file(path),
                    "visual_hash": visual_hash,
                    "brightness": brightness,
                }
            )
        except (ParsingError, OSError) as exc:
            errors.append({"file": relative_path, "error": str(exc)})

    pairs: list[dict[str, Any]] = []
    search_tree: _HashSearchNode | None = None
    for second_index, second in enumerate(fingerprints):
        candidate_indices = (
            search_tree.search(second["visual_hash"], perceptual_distance)
            if search_tree is not None
            else []
        )
        for first_index in candidate_indices:
            first = fingerprints[first_index]
            exact = first["sha256"] == second["sha256"]
            distance = (first["visual_hash"] ^ second["visual_hash"]).bit_count()
            brightness_difference = abs(first["brightness"] - second["brightness"])
            if not exact and (
                distance > perceptual_distance
                or brightness_difference > brightness_tolerance
            ):
                continue
            pairs.append(
                {
                    "code": "exact_duplicate" if exact else "perceptual_duplicate",
                    "files": [first["file"], second["file"]],
                    "hamming_distance": distance,
                    "brightness_difference": round(brightness_difference, 3),
                    "sha256": first["sha256"] if exact else None,
                }
            )
        if search_tree is None:
            search_tree = _HashSearchNode(second["visual_hash"], second_index)
        else:
            search_tree.insert(second["visual_hash"], second_index)

    return {
        "images_scanned": len(paths),
        "images_hashed": len(fingerprints),
        "inventory": [
            {
                "file": item["file"],
                "sha256": item["sha256"],
                "perceptual_hash": f"{item['visual_hash']:032x}",
            }
            for item in fingerprints
        ],
        "pairs": pairs,
        "errors": errors,
    }


def find_dataset_alignment_issues(
    image_root: str | Path,
    annotation_root: str | Path,
) -> list[dict[str, str]]:
    """이미지와 JSON이 같은 stem으로 일대일 대응하는지 확인한다."""
    image_base = Path(image_root)
    annotation_base = Path(annotation_root)
    image_paths = collect_image_paths(image_base)
    if not annotation_base.is_dir():
        raise ParsingError(
            f"Annotation root must be an existing directory: {annotation_base}"
        )
    annotation_paths = sorted(
        (
            path
            for path in annotation_base.rglob("*.json")
            if path.is_file()
        ),
        key=lambda path: path.relative_to(annotation_base).as_posix().lower(),
    )

    image_by_stem: dict[str, list[Path]] = {}
    annotation_by_stem: dict[str, list[Path]] = {}
    for path in image_paths:
        image_by_stem.setdefault(path.stem.casefold(), []).append(path)
    for path in annotation_paths:
        annotation_by_stem.setdefault(path.stem.casefold(), []).append(path)

    issues: list[dict[str, str]] = []
    for stem, paths in sorted(image_by_stem.items()):
        if len(paths) > 1:
            issues.append(
                {
                    "code": "duplicate_image_stem",
                    "file": ", ".join(
                        path.relative_to(image_base.resolve()).as_posix()
                        for path in paths
                    ),
                    "error": f"Multiple images use the same stem '{stem}'.",
                }
            )
        if stem not in annotation_by_stem:
            for path in paths:
                relative_path = path.relative_to(image_base.resolve()).as_posix()
                issues.append(
                    {
                        "code": "missing_annotation",
                        "file": relative_path,
                        "error": "Image has no matching annotation JSON.",
                    }
                )

    for stem, paths in sorted(annotation_by_stem.items()):
        if len(paths) > 1:
            issues.append(
                {
                    "code": "duplicate_annotation_stem",
                    "file": ", ".join(
                        path.relative_to(annotation_base).as_posix() for path in paths
                    ),
                    "error": f"Multiple annotation files use the same stem '{stem}'.",
                }
            )
        if stem not in image_by_stem:
            for path in paths:
                issues.append(
                    {
                        "code": "missing_image",
                        "file": path.relative_to(annotation_base).as_posix(),
                        "error": "Annotation JSON has no matching image.",
                    }
                )
    return issues


def summarize_issue_codes(issues: Sequence[dict[str, Any]]) -> dict[str, int]:
    """대시보드와 manifest가 공유할 issue code별 개수를 만든다."""
    return dict(sorted(Counter(str(issue["code"]) for issue in issues).items()))
