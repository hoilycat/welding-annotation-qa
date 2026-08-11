import json
from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from welding_qa.dataset_qa import (
    find_annotation_issues,
    find_dataset_alignment_issues,
    find_duplicate_images,
)
from welding_qa.models import ParsingError
from welding_qa.taxonomy import TaxonomyConfig


def _write_annotations(path: Path, annotations: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "modality": "RT",
                "image_info": {
                    "filename": path.stem + ".png",
                    "width": 100,
                    "height": 100,
                },
                "annotations": annotations,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _rectangle(label: str, left: int, top: int, right: int, bottom: int) -> dict[str, object]:
    return {
        "label": label,
        "polygon": {
            "x": [left, right, right, left],
            "y": [top, top, bottom, bottom],
        },
    }


def test_find_annotation_issues_reports_overlapping_different_labels(tmp_path: Path):
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
    _write_annotations(
        tmp_path / "sample.json",
        [
            _rectangle("기공", 10, 10, 60, 60),
            _rectangle("균열", 30, 30, 80, 80),
        ],
    )

    issues = find_annotation_issues(tmp_path, taxonomy)

    assert len(issues) == 1
    assert issues[0]["code"] == "label_conflict"
    assert issues[0]["severity"] == "error"
    assert issues[0]["labels"] == ["porosity", "crack"]
    assert issues[0]["smaller_overlap_ratio"] > 0.3


def test_find_annotation_issues_reports_nearly_identical_same_label(tmp_path: Path):
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
    _write_annotations(
        tmp_path / "sample.json",
        [
            _rectangle("기공", 10, 10, 70, 70),
            _rectangle("porosity", 11, 11, 69, 69),
        ],
    )

    issues = find_annotation_issues(tmp_path, taxonomy)

    assert len(issues) == 1
    assert issues[0]["code"] == "possible_duplicate_annotation"
    assert issues[0]["iou"] >= 0.9


def test_find_annotation_issues_ignores_separate_polygons_and_invalid_files(tmp_path: Path):
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
    _write_annotations(
        tmp_path / "sample.json",
        [
            _rectangle("기공", 5, 5, 20, 20),
            _rectangle("균열", 70, 70, 90, 90),
        ],
    )
    (tmp_path / "invalid.json").write_text("{invalid", encoding="utf-8")

    assert find_annotation_issues(tmp_path, taxonomy) == []


def test_find_annotation_issues_validates_thresholds(tmp_path: Path):
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")

    with pytest.raises(ParsingError, match="Overlap threshold"):
        find_annotation_issues(tmp_path, taxonomy, overlap_threshold=1.1)


def _make_test_image(path: Path, *, offset: int = 0) -> None:
    image = Image.new("L", (64, 64), color=210)
    draw = ImageDraw.Draw(image)
    draw.ellipse((12 + offset, 16, 40 + offset, 44), fill=35)
    image.save(path)


def test_find_duplicate_images_separates_exact_and_perceptual_matches(tmp_path: Path):
    _make_test_image(tmp_path / "first.png")
    (tmp_path / "second.png").write_bytes((tmp_path / "first.png").read_bytes())
    with Image.open(tmp_path / "first.png") as image:
        image.save(tmp_path / "third.bmp")

    result = find_duplicate_images(tmp_path)

    codes = [pair["code"] for pair in result["pairs"]]
    assert result["images_scanned"] == 3
    assert codes.count("exact_duplicate") == 1
    assert codes.count("perceptual_duplicate") == 2


def test_find_duplicate_images_ignores_visually_different_images(tmp_path: Path):
    _make_test_image(tmp_path / "first.png")
    _make_test_image(tmp_path / "second.png", offset=20)

    result = find_duplicate_images(tmp_path, perceptual_distance=0)

    assert result["pairs"] == []


def test_find_duplicate_images_validates_distance(tmp_path: Path):
    with pytest.raises(ParsingError, match="Perceptual distance"):
        find_duplicate_images(tmp_path, perceptual_distance=129)


def test_find_dataset_alignment_issues_reports_both_missing_sides(tmp_path: Path):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    image_root.mkdir()
    annotation_root.mkdir()
    _make_test_image(image_root / "image-only.png")
    _write_annotations(annotation_root / "json-only.json", [])

    issues = find_dataset_alignment_issues(image_root, annotation_root)

    assert [issue["code"] for issue in issues] == [
        "missing_annotation",
        "missing_image",
    ]


def test_find_dataset_alignment_issues_accepts_matching_stems(tmp_path: Path):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    image_root.mkdir()
    annotation_root.mkdir()
    _make_test_image(image_root / "sample.png")
    _write_annotations(annotation_root / "sample.json", [])

    assert find_dataset_alignment_issues(image_root, annotation_root) == []
