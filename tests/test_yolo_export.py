import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest
import yaml

from welding_qa.coco_export import build_coco_dataset
from welding_qa.models import DefectAnnotation, ParsingError, Polygon
from welding_qa.taxonomy import TaxonomyConfig
from welding_qa.yolo_export import (
    annotation_to_yolo_segment,
    build_yolo_dataset,
    export_yolo_dataset,
    main,
)


def _write_image(path: Path, *, size: tuple[int, int] = (100, 80)) -> None:
    """테스트에서 실제 Pillow 검증을 통과할 작은 grayscale 이미지를 만든다."""
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
    """실제 reader가 처리하는 RIAWELC 호환 JSON fixture를 기록한다."""
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
    """결함 label로 내보내지 않아야 하는 실제 RIAWELC normal 영역을 만든다."""
    return {
        "class": "normal",
        "case": "",
        "coordinate": {"x": [1, 90, 90, 1], "y": [1, 1, 70, 70]},
    }


def _slag_polygon() -> dict[str, object]:
    """정규화 좌표를 손으로 검산하기 쉬운 슬러그 삼각형을 만든다."""
    return {
        "class": "defect",
        "case": "slag inclusion",
        "coordinate": {"x": [10, 30, 20], "y": [10, 10, 30]},
    }


def _boundary_porosity_polygon() -> dict[str, object]:
    """이미지 네 경계의 0/1 정규화가 정확한지 확인할 기공 삼각형을 만든다."""
    return {
        "class": "defect",
        "case": "porosity",
        "coordinate": {"x": [0, 100, 0], "y": [0, 0, 80]},
    }


def test_export_yolo_dataset_copies_images_and_writes_normal_and_slag_labels(
    tmp_path: Path,
):
    image_root = tmp_path / "source" / "images"
    annotation_root = tmp_path / "source" / "annotations"
    output = tmp_path / "exports" / "yolo"
    _write_image(image_root / "batch" / "normal.png")
    _write_image(image_root / "batch" / "mixed.png")
    _write_json(annotation_root / "normal.json", "normal.png", [_normal_polygon()])
    _write_json(
        annotation_root / "mixed.json",
        "mixed.png",
        [_normal_polygon(), _slag_polygon()],
    )

    result = export_yolo_dataset(
        image_root,
        annotation_root,
        output,
        TaxonomyConfig.load_default(),
    )

    assert result == {
        "images": 2,
        "annotations": 1,
        "classes": 6,
        "output": str(output),
    }
    assert (output / "images/batch/mixed.png").read_bytes() == (
        image_root / "batch/mixed.png"
    ).read_bytes()
    assert (output / "labels/batch/normal.txt").read_text(encoding="utf-8") == ""
    assert (output / "labels/batch/mixed.txt").read_text(encoding="utf-8") == (
        "1 0.1 0.125 0.3 0.125 0.2 0.375\n"
    )

    classes = yaml.safe_load((output / "classes.yaml").read_text(encoding="utf-8"))
    assert classes["names"] == {
        0: "porosity",
        1: "slag_inclusion",
        2: "crack",
        3: "lack_of_fusion",
        4: "incomplete_penetration",
        5: "undercut",
    }
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert [item["annotations"] for item in manifest["images"]] == [1, 0]
    assert "source_path" not in manifest["images"][0]
    assert manifest["images"][0]["sha256"] == hashlib.sha256(
        (output / "images/batch/mixed.png").read_bytes()
    ).hexdigest()


def test_yolo_and_coco_use_the_same_images_categories_and_annotation_count(
    tmp_path: Path,
):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    _write_image(image_root / "slag.png")
    _write_json(annotation_root / "slag.json", "slag.png", [_slag_polygon()])
    taxonomy = TaxonomyConfig.load_default()

    yolo = build_yolo_dataset(image_root, annotation_root, taxonomy)
    coco = build_coco_dataset(image_root, annotation_root, taxonomy)

    assert len(yolo["items"]) == len(coco["images"]) == 1
    assert sum(item["annotations"] for item in yolo["items"]) == len(
        coco["annotations"]
    )
    assert list(yolo["names"].values()) == [
        category["name"] for category in coco["categories"]
    ]
    # COCO는 1-based, YOLO는 0-based이므로 같은 slug의 ID가 정확히 1 차이 난다.
    assert coco["annotations"][0]["category_id"] == 2
    assert yolo["items"][0]["label_text"].startswith("1 ")


def test_export_yolo_dataset_refuses_to_overwrite_existing_directory(tmp_path: Path):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    output = tmp_path / "existing"
    _write_image(image_root / "clean.png")
    _write_json(annotation_root / "clean.json", "clean.png", [])
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("user data", encoding="utf-8")

    with pytest.raises(ParsingError, match="already exists"):
        export_yolo_dataset(
            image_root,
            annotation_root,
            output,
            TaxonomyConfig.load_default(),
        )

    assert marker.read_text(encoding="utf-8") == "user data"
    assert list(output.iterdir()) == [marker]


def test_export_yolo_dataset_does_not_leave_output_on_validation_error(
    tmp_path: Path,
):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    output = tmp_path / "exports" / "invalid"
    _write_image(image_root / "slag.png")
    _write_json(annotation_root / "slag.json", "different.png", [_slag_polygon()])

    with pytest.raises(ParsingError, match="does not match actual image"):
        export_yolo_dataset(
            image_root,
            annotation_root,
            output,
            TaxonomyConfig.load_default(),
        )

    assert not output.exists()
    if output.parent.exists():
        assert not list(output.parent.glob(".*-staging-*"))


def test_export_yolo_dataset_cleans_staging_directory_when_copy_fails(
    tmp_path: Path,
    monkeypatch,
):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    output = tmp_path / "exports" / "copy-failure"
    _write_image(image_root / "clean.png")
    _write_json(annotation_root / "clean.json", "clean.png", [])

    def fail_copy(*_args, **_kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("welding_qa.yolo_export.shutil.copy2", fail_copy)
    with pytest.raises(OSError, match="simulated disk failure"):
        export_yolo_dataset(
            image_root,
            annotation_root,
            output,
            TaxonomyConfig.load_default(),
        )

    assert not output.exists()
    assert output.parent.is_dir()
    assert not list(output.parent.glob(".*-staging-*"))


def test_yolo_normalization_preserves_zero_and_one_image_boundaries(tmp_path: Path):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    _write_image(image_root / "porosity.png", size=(100, 80))
    _write_json(
        annotation_root / "porosity.json",
        "porosity.png",
        [_boundary_porosity_polygon()],
    )

    dataset = build_yolo_dataset(
        image_root,
        annotation_root,
        TaxonomyConfig.load_default(),
    )

    assert dataset["items"][0]["label_text"] == "0 0 0 1 0 0 1\n"


@pytest.mark.parametrize(
    ("class_ids", "width", "error"),
    [
        ({"porosity": True}, 100, "non-negative integer"),
        ({"porosity": 0}, 0, "positive finite"),
    ],
)
def test_annotation_to_yolo_segment_rejects_invalid_direct_api_arguments(
    class_ids: dict[str, object],
    width: int,
    error: str,
):
    annotation = DefectAnnotation(
        label_original="porosity",
        label_canonical="porosity",
        polygon=Polygon(x=(0, 10, 0), y=(0, 0, 10)),
    )

    with pytest.raises(ParsingError, match=error):
        annotation_to_yolo_segment(
            annotation,
            class_ids,  # type: ignore[arg-type] - intentionally invalid public input
            width=width,
            height=80,
        )


def test_yolo_export_accepts_windows_metadata_path_on_other_platforms(tmp_path: Path):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    _write_image(image_root / "slag.png")
    _write_json(
        annotation_root / "slag.json",
        r"C:\dataset\slag.png",
        [_slag_polygon()],
    )

    dataset = build_yolo_dataset(
        image_root,
        annotation_root,
        TaxonomyConfig.load_default(),
    )

    assert dataset["items"][0]["annotations"] == 1


def test_yolo_export_rejects_corrupt_image_before_creating_output(tmp_path: Path):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    output = tmp_path / "yolo"
    image_root.mkdir()
    (image_root / "broken.png").write_bytes(b"not an image")
    _write_json(annotation_root / "broken.json", "broken.png", [])

    with pytest.raises(ParsingError, match="Could not read image"):
        export_yolo_dataset(
            image_root,
            annotation_root,
            output,
            TaxonomyConfig.load_default(),
        )

    assert not output.exists()


def test_export_yolo_dataset_can_keep_missing_json_as_empty_label(tmp_path: Path):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    output = tmp_path / "yolo"
    _write_image(image_root / "clean.png")
    annotation_root.mkdir()

    export_yolo_dataset(
        image_root,
        annotation_root,
        output,
        TaxonomyConfig.load_default(),
        allow_missing_annotations=True,
    )

    assert (output / "images/clean.png").is_file()
    assert (output / "labels/clean.txt").read_bytes() == b""


def test_yolo_export_cli_uses_packaged_taxonomy_and_prints_summary(
    tmp_path: Path,
    capsys,
):
    image_root = tmp_path / "images"
    annotation_root = tmp_path / "annotations"
    output = tmp_path / "yolo"
    _write_image(image_root / "slag.png")
    _write_json(annotation_root / "slag.json", "slag.png", [_slag_polygon()])

    exit_code = main(
        [
            "--images",
            str(image_root),
            "--annotations",
            str(annotation_root),
            "--output-dir",
            str(output),
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "images": 1,
        "annotations": 1,
        "classes": 6,
        "output": str(output),
    }
