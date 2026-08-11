import json
from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from welding_qa.dashboard import render_dashboard
from welding_qa.models import ParsingError
from welding_qa.release_report import (
    build_release_manifest,
    main,
    write_release_bundle,
)
from welding_qa.taxonomy import TaxonomyConfig


def _write_dataset(root: Path, *, invalid: bool = False) -> tuple[Path, Path]:
    image_root = root / "images"
    annotation_root = root / "annotations"
    image_root.mkdir()
    annotation_root.mkdir()

    image = Image.new("L", (80, 60), color=190)
    ImageDraw.Draw(image).ellipse((20, 16, 42, 38), fill=25)
    image.save(image_root / "sample.png")

    annotation_path = annotation_root / "sample.json"
    if invalid:
        annotation_path.write_text("{invalid", encoding="utf-8")
    else:
        annotation_path.write_text(
            json.dumps(
                {
                    "modality": "RT",
                    "image_info": {
                        "filename": "sample.png",
                        "width": 80,
                        "height": 60,
                    },
                    "annotations": [
                        {
                            "label": "기공",
                            "polygon": {
                                "x": [20, 42, 42, 20],
                                "y": [16, 16, 38, 38],
                            },
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return image_root, annotation_root


def test_build_release_manifest_contains_checksums_and_passed_status(tmp_path: Path):
    image_root, annotation_root = _write_dataset(tmp_path)
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")

    manifest = build_release_manifest(
        image_root,
        annotation_root,
        taxonomy,
        modality="RT",
    )

    assert manifest["status"] == "passed"
    assert manifest["status_reasons"][0]["code"] == "all_checks_clear"
    assert manifest["summary"] == {
        "images": 1,
        "valid_files": 1,
        "invalid_files": 0,
        "annotations": 1,
        "review_items": 0,
        "duplicate_images": 0,
        "duplicate_pairs": 0,
        "blocking_errors": 0,
    }
    assert len(manifest["dataset_digest"]) == 64
    assert manifest["inventory"]["images"][0]["file"] == "sample.png"
    assert manifest["inventory"]["annotations"][0]["file"] == "sample.json"
    assert manifest["sources"] == {
        "image_root": "<images>",
        "annotation_root": "<annotations>",
        "paths_redacted": True,
    }
    assert str(tmp_path) not in json.dumps(manifest)


def test_build_release_manifest_marks_invalid_json_as_failed(tmp_path: Path):
    image_root, annotation_root = _write_dataset(tmp_path, invalid=True)
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")

    manifest = build_release_manifest(image_root, annotation_root, taxonomy)

    assert manifest["status"] == "failed"
    assert manifest["summary"]["blocking_errors"] == 1
    assert manifest["status_reasons"][0]["code"] == "invalid_annotation_files"


def test_build_release_manifest_marks_overlap_candidate_for_review(tmp_path: Path):
    image_root, annotation_root = _write_dataset(tmp_path)
    annotation_path = annotation_root / "sample.json"
    payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    payload["annotations"].append(dict(payload["annotations"][0]))
    annotation_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")

    manifest = build_release_manifest(image_root, annotation_root, taxonomy)

    assert manifest["status"] == "review"
    assert manifest["status_reasons"][0]["code"] == "annotation_review_candidates"
    assert manifest["checks"]["annotation_issue_counts"] == {
        "possible_duplicate_annotation": 1
    }


def test_build_release_manifest_marks_label_conflict_as_failed(tmp_path: Path):
    image_root, annotation_root = _write_dataset(tmp_path)
    annotation_path = annotation_root / "sample.json"
    payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    payload["annotations"].append(
        {
            "label": "균열",
            "polygon": {
                "x": [24, 46, 46, 24],
                "y": [20, 20, 42, 42],
            },
        }
    )
    annotation_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")

    manifest = build_release_manifest(image_root, annotation_root, taxonomy)

    assert manifest["status"] == "failed"
    assert manifest["summary"]["blocking_errors"] == 1
    assert manifest["status_reasons"][0]["code"] == "annotation_blocking_errors"
    assert manifest["checks"]["annotation_issue_counts"] == {"label_conflict": 1}


def test_render_dashboard_uses_weldvision_theme_and_real_summary(tmp_path: Path):
    image_root, annotation_root = _write_dataset(tmp_path)
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
    manifest = build_release_manifest(image_root, annotation_root, taxonomy)

    dashboard = render_dashboard(manifest)

    assert "🔥 Welding QA" in dashboard
    assert "WeldVision · Annotation Control" in dashboard
    assert "검수 통과" in dashboard
    assert "왜 이 상태로 판정됐나요?" in dashboard
    assert "Hash 거리" in dashboard
    assert "porosity" in dashboard
    assert manifest["dataset_digest"] in dashboard


def test_write_release_bundle_creates_all_artifacts_atomically(tmp_path: Path):
    image_root, annotation_root = _write_dataset(tmp_path)
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
    manifest = build_release_manifest(image_root, annotation_root, taxonomy)
    output_dir = tmp_path / "release"

    result = write_release_bundle(manifest, output_dir)

    assert result == output_dir
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "dashboard.html",
        "qa-report.json",
        "release-manifest.json",
    ]
    assert json.loads(
        (output_dir / "release-manifest.json").read_text(encoding="utf-8")
    )["status"] == "passed"


def test_write_release_bundle_refuses_existing_directory(tmp_path: Path):
    output_dir = tmp_path / "release"
    output_dir.mkdir()

    with pytest.raises(ParsingError, match="already exists"):
        write_release_bundle({"qa": {}}, output_dir)


def test_release_bundle_adds_side_by_side_duplicate_thumbnails(tmp_path: Path):
    image_root, annotation_root = _write_dataset(tmp_path)
    with Image.open(image_root / "sample.png") as image:
        image.save(image_root / "similar.bmp")
    (annotation_root / "similar.json").write_text(
        json.dumps(
            {
                "modality": "RT",
                "image_info": {
                    "filename": "similar.bmp",
                    "width": 80,
                    "height": 60,
                },
                "annotations": [],
            }
        ),
        encoding="utf-8",
    )
    taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
    manifest = build_release_manifest(image_root, annotation_root, taxonomy)
    output_dir = tmp_path / "release"

    write_release_bundle(manifest, output_dir, image_root=image_root)

    assert manifest["summary"]["duplicate_images"] == 2
    assert manifest["summary"]["duplicate_pairs"] == 1
    assert len(list((output_dir / "thumbnails").glob("*.jpg"))) == 2
    dashboard = (output_dir / "dashboard.html").read_text(encoding="utf-8")
    assert "유사 이미지 비교 · 2장 / 1쌍" in dashboard
    assert 'src="thumbnails/candidate-001.jpg"' in dashboard
    assert "중복 확정은 아닙니다" in dashboard


def test_release_report_cli_writes_dashboard(tmp_path: Path):
    image_root, annotation_root = _write_dataset(tmp_path)
    output_dir = tmp_path / "release"

    exit_code = main(
        [
            "--images",
            str(image_root),
            "--annotations",
            str(annotation_root),
            "--modality",
            "RT",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "dashboard.html").is_file()
