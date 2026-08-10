import json
from pathlib import Path

import pytest

from welding_qa.models import ParsingError
from welding_qa.smoke_validation import validate_smoke_export
from welding_qa.taxonomy import TaxonomyConfig


def _write_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"smoke-test-image")


def _write_annotation(path: Path, *, label: str = "porosity", x: int = 10) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "modality": "RT",
                "image_info": {
                    "filename": path.stem + ".jpg",
                    "width": 100,
                    "height": 100,
                },
                "annotations": [
                    {
                        "label": label,
                        "polygon": {
                            "x": [x, x + 20, x + 10],
                            "y": [10, 10, 30],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_validate_smoke_export_accepts_exact_round_trip(tmp_path: Path):
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
    _write_image(tmp_path / "images" / "001.jpg")
    _write_annotation(tmp_path / "annotations" / "001.json", label="기공")
    _write_annotation(tmp_path / "export" / "001.json", label="porosity")

    result = validate_smoke_export(
        tmp_path / "images",
        tmp_path / "export",
        taxonomy,
        modality="RT",
        annotation_root=tmp_path / "annotations",
    )

    assert result == {
        "images": 1,
        "annotations_expected": 1,
        "annotations_exported": 1,
        "round_trip_exact": True,
    }


@pytest.mark.parametrize(
    ("label", "x"),
    [("crack", 10), ("porosity", 11)],
)
def test_validate_smoke_export_rejects_label_or_coordinate_changes(
    tmp_path: Path,
    label: str,
    x: int,
):
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
    _write_image(tmp_path / "images" / "001.jpg")
    _write_annotation(tmp_path / "annotations" / "001.json")
    _write_annotation(tmp_path / "export" / "001.json", label=label, x=x)

    with pytest.raises(ParsingError, match="do not match the input"):
        validate_smoke_export(
            tmp_path / "images",
            tmp_path / "export",
            taxonomy,
            modality="RT",
            annotation_root=tmp_path / "annotations",
        )


def test_validate_smoke_export_without_annotations_requires_empty_export(
    tmp_path: Path,
):
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
    _write_image(tmp_path / "images" / "001.jpg")
    _write_annotation(tmp_path / "export" / "001.json")

    with pytest.raises(ParsingError, match="do not match the input"):
        validate_smoke_export(
            tmp_path / "images",
            tmp_path / "export",
            taxonomy,
            modality="RT",
        )
