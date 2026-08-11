import json
from pathlib import Path

from PIL import Image
import pytest

from welding_qa.coco_export import build_coco_dataset, main
from welding_qa.models import ParsingError
from welding_qa.taxonomy import TaxonomyConfig


def _write_image(path: Path, *, size: tuple[int, int] = (100, 80)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", size, color=0).save(path)


def _write_json(
    path: Path,
    filename: str,
    annotations: list[dict[str, object]],
    *,
    width: int = 100,
    height: int = 80,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "modality": "RT",
                "image_info": {
                    "filename": filename,
                    "width": width,
                    "height": height,
                },
                "annotations": annotations,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _normal_polygon() -> dict[str, object]:
    return {
        "class": "normal",
        "case": "",
        "coordinate": {"x": [1, 90, 90, 1], "y": [1, 1, 70, 70]},
    }


def _slag_polygon() -> dict[str, object]:
    return {
        "class": "defect",
        "case": "slag inclusion",
        "coordinate": {"x": [10, 30, 20], "y": [10, 10, 30]},
    }


def test_build_coco_dataset_keeps_normal_image_and_exports_mixed_slag(
    tmp_path: Path,
):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    _write_image(image_root / "batch" / "normal.png")
    _write_image(image_root / "batch" / "mixed.png")
    _write_json(annotation_root / "normal.json", "normal.png", [_normal_polygon()])
    _write_json(
        annotation_root / "mixed.json",
        "mixed.png",
        [_normal_polygon(), _slag_polygon()],
    )

    dataset = build_coco_dataset(
        image_root,
        annotation_root,
        TaxonomyConfig.load_default(),
        modality="RT",
    )

    assert dataset["images"] == [
        {"id": 1, "file_name": "batch/mixed.png", "width": 100, "height": 80},
        {"id": 2, "file_name": "batch/normal.png", "width": 100, "height": 80},
    ]
    assert [category["name"] for category in dataset["categories"]] == [
        "porosity",
        "slag_inclusion",
        "crack",
        "lack_of_fusion",
        "incomplete_penetration",
        "undercut",
    ]
    assert dataset["annotations"] == [
        {
            "id": 1,
            "image_id": 1,
            "category_id": 2,
            "segmentation": [[10.0, 10.0, 30.0, 10.0, 20.0, 30.0]],
            "area": 200.0,
            "bbox": [10.0, 10.0, 20.0, 20.0],
            "iscrowd": 0,
        }
    ]


def test_build_coco_dataset_rejects_metadata_dimension_mismatch(tmp_path: Path):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    _write_image(image_root / "slag.png", size=(100, 80))
    _write_json(
        annotation_root / "slag.json",
        "slag.png",
        [_slag_polygon()],
        width=101,
    )

    with pytest.raises(ParsingError, match="width 101.*actual image width 100"):
        build_coco_dataset(
            image_root,
            annotation_root,
            TaxonomyConfig.load_default(),
        )


def test_build_coco_dataset_validates_polygon_against_actual_image(tmp_path: Path):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    _write_image(image_root / "slag.png", size=(20, 20))
    _write_json(
        annotation_root / "slag.json",
        "slag.png",
        [_slag_polygon()],
        width=20,
        height=20,
    )

    with pytest.raises(ParsingError, match="outside image bounds"):
        build_coco_dataset(
            image_root,
            annotation_root,
            TaxonomyConfig.load_default(),
        )


def test_build_coco_dataset_can_keep_image_without_json(tmp_path: Path):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    _write_image(image_root / "clean.png")
    annotation_root.mkdir()

    dataset = build_coco_dataset(
        image_root,
        annotation_root,
        TaxonomyConfig.load_default(),
        allow_missing_annotations=True,
    )

    assert len(dataset["images"]) == 1
    assert dataset["annotations"] == []


def test_coco_export_cli_writes_json_with_packaged_taxonomy(tmp_path: Path):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    output = tmp_path / "exports" / "dataset.json"
    _write_image(image_root / "slag.png")
    _write_json(annotation_root / "slag.json", "slag.png", [_slag_polygon()])

    exit_code = main(
        [
            "--images",
            str(image_root),
            "--annotations",
            str(annotation_root),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    dataset = json.loads(output.read_text(encoding="utf-8"))
    assert len(dataset["images"]) == 1
    assert dataset["annotations"][0]["category_id"] == 2


def test_coco_export_cli_does_not_write_partial_output_on_validation_error(
    tmp_path: Path,
):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    output = tmp_path / "exports" / "dataset.json"
    _write_image(image_root / "slag.png", size=(100, 80))
    _write_json(
        annotation_root / "slag.json",
        "different.png",
        [_slag_polygon()],
    )

    exit_code = main(
        [
            "--images",
            str(image_root),
            "--annotations",
            str(annotation_root),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 1
    assert not output.exists()
