import json
from pathlib import Path

from welding_qa.qa_report import build_qa_report
from welding_qa.taxonomy import TaxonomyConfig


def _write_annotation(path: Path, *, label: str = "기공", modality: str = "RT") -> None:
    path.write_text(
        json.dumps(
            {
                "modality": modality,
                "image_info": {"filename": path.stem + ".png", "width": 100, "height": 100},
                "annotations": [
                    {"label": label, "polygon": {"x": [10, 30, 20], "y": [10, 10, 30]}}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_build_qa_report_counts_valid_files_and_labels(tmp_path: Path):
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
    _write_annotation(tmp_path / "001.json")
    (tmp_path / "002.json").write_text(
        json.dumps({"modality": "RT", "image_info": {"width": 100, "height": 100}, "annotations": []}),
        encoding="utf-8",
    )

    report = build_qa_report(tmp_path, taxonomy, modality="RT")

    assert report["files_total"] == 2
    assert report["files_valid"] == 2
    assert report["annotation_count"] == 1
    assert report["label_counts"] == {"porosity": 1}
    assert report["modality_counts"] == {"RT": 2}


def test_build_qa_report_collects_invalid_files(tmp_path: Path):
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
    _write_annotation(tmp_path / "good.json")
    (tmp_path / "bad.json").write_text("{invalid", encoding="utf-8")

    report = build_qa_report(tmp_path, taxonomy)

    assert report["files_valid"] == 1
    assert report["files_invalid"] == 1
    assert report["errors"][0]["file"] == "bad.json"


def test_build_qa_report_rejects_wrong_modality(tmp_path: Path):
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
    _write_annotation(tmp_path / "001.json", modality="VT")

    report = build_qa_report(tmp_path, taxonomy, modality="RT")

    assert report["files_invalid"] == 1
    assert "does not match expected modality" in report["errors"][0]["error"]
