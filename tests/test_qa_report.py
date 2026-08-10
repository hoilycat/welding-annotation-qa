import json
from pathlib import Path

from welding_qa.qa_report import build_qa_report, main
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


def test_build_qa_report_counts_empty_file_modality_without_filter(tmp_path: Path):
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
    (tmp_path / "empty.json").write_text(
        json.dumps({"info": {"type": "VT"}, "annotations": []}),
        encoding="utf-8",
    )

    report = build_qa_report(tmp_path, taxonomy)

    assert report["modality_counts"] == {"VT": 1}


def test_qa_report_cli_returns_failure_but_writes_invalid_report(
    tmp_path: Path,
):
    annotation_dir = tmp_path / "annotations"
    annotation_dir.mkdir()
    (annotation_dir / "bad.json").write_text("{invalid", encoding="utf-8")
    output_path = tmp_path / "report.json"

    exit_code = main(
        [
            "--annotations",
            str(annotation_dir),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    assert json.loads(output_path.read_text(encoding="utf-8"))["files_invalid"] == 1


def test_qa_report_cli_uses_packaged_taxonomy_outside_repository(
    tmp_path: Path,
    monkeypatch,
):
    annotation_dir = tmp_path / "annotations"
    annotation_dir.mkdir()
    _write_annotation(annotation_dir / "001.json")
    output_path = tmp_path / "report.json"
    working_dir = tmp_path / "outside-repository"
    working_dir.mkdir()
    monkeypatch.chdir(working_dir)

    exit_code = main(
        [
            "--annotations",
            str(annotation_dir),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["label_counts"] == {
        "porosity": 1
    }
