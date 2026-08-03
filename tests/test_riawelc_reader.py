import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest
from welding_qa.models import ParsingError
from welding_qa.riawelc_reader import parse_riawelc_json
from welding_qa.taxonomy import TaxonomyConfig


@pytest.fixture
def taxonomy() -> TaxonomyConfig:
    yaml_path = Path(__file__).resolve().parents[1] / "configs" / "taxonomy.yaml"
    return TaxonomyConfig.load_from_yaml(yaml_path)


@pytest.fixture
def sample_json_path() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "sample_annotation.json"


def test_parse_valid_fixture(taxonomy: TaxonomyConfig, sample_json_path: Path):
    defects = parse_riawelc_json(sample_json_path, taxonomy)
    assert len(defects) == 1
    
    det = defects[0]
    assert det.label_original == "기공"
    assert det.label_canonical == "porosity"
    assert det.modality == "RT"
    assert len(det.polygon.x) == 4
    assert len(det.polygon.y) == 4
    assert det.extra_meta == {
        "image_id": "SAMPLE_0001",
        "filename": "sample_weld_001.png",
        "width": 800,
        "height": 600,
    }


def test_parse_empty_annotations_returns_empty_list(taxonomy: TaxonomyConfig):
    assert parse_riawelc_json({"annotations": []}, taxonomy) == []


def test_parse_non_object_annotation_raises_error(taxonomy: TaxonomyConfig):
    with pytest.raises(ParsingError, match="Annotation item at index 0 must be a dictionary object"):
        parse_riawelc_json({"annotations": ["invalid"]}, taxonomy)


def test_parse_disallowed_modality_raises_error(taxonomy: TaxonomyConfig):
    invalid_data = {
        "modality": "INVALID",
        "annotations": [
            {
                "label": "porosity",
                "polygon": {
                    "x": [10.0, 20.0, 30.0],
                    "y": [10.0, 20.0, 30.0],
                },
            }
        ],
    }
    with pytest.raises(ParsingError, match="Modality 'INVALID' is not allowed"):
        parse_riawelc_json(invalid_data, taxonomy)


def test_parse_coordinate_mismatch_raises_error(taxonomy: TaxonomyConfig):
    invalid_data = {
        "modality": "RT",
        "annotations": [
            {
                "label": "porosity",
                "polygon": {
                    "x": [10.0, 20.0, 30.0],       # 3 elements
                    "y": [10.0, 20.0, 30.0, 40.0]  # 4 elements -> MISMATCH!
                }
            }
        ]
    }
    with pytest.raises(ParsingError, match="x and y coordinate lengths mismatch"):
        parse_riawelc_json(invalid_data, taxonomy)
