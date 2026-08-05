from pathlib import Path

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


def test_parse_invalid_json_string_raises_parsing_error(taxonomy: TaxonomyConfig):
    with pytest.raises(ParsingError, match="Invalid JSON content"):
        parse_riawelc_json('{"annotations": [}', taxonomy)


def test_parse_unknown_label_raises_parsing_error(taxonomy: TaxonomyConfig):
    with pytest.raises(
        ParsingError,
        match="Annotation item at index 0 has invalid label: Unknown label 'not-a-defect'",
    ):
        parse_riawelc_json(
            {
                "annotations": [
                    {
                        "label": "not-a-defect",
                        "polygon": {"x": [1, 2, 3], "y": [1, 2, 3]},
                    }
                ]
            },
            taxonomy,
        )


@pytest.mark.parametrize("annotations", [{}, "invalid", None])
def test_parse_non_list_annotations_raises_error(
    taxonomy: TaxonomyConfig, annotations: object
):
    with pytest.raises(ParsingError, match="Field 'annotations' must be a list"):
        parse_riawelc_json({"annotations": annotations}, taxonomy)


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
    with pytest.raises(ParsingError, match="modality 'INVALID' is not allowed"):
        parse_riawelc_json(invalid_data, taxonomy)


@pytest.mark.parametrize("modality", [0, False, None])
def test_parse_non_string_modality_raises_parsing_error(
    taxonomy: TaxonomyConfig, modality: object
):
    invalid_data = {
        "modality": modality,
        "annotations": [
            {
                "label": "porosity",
                "polygon": {"x": [1, 2, 3], "y": [1, 2, 3]},
            }
        ],
    }
    with pytest.raises(ParsingError, match="Field 'modality' must be a string"):
        parse_riawelc_json(invalid_data, taxonomy)


def test_parse_empty_modality_is_not_replaced_by_default(taxonomy: TaxonomyConfig):
    with pytest.raises(ParsingError, match="Field 'modality' must not be empty"):
        parse_riawelc_json({"modality": "", "annotations": []}, taxonomy)


def test_parse_whitespace_modality_is_not_accepted(taxonomy: TaxonomyConfig):
    with pytest.raises(ParsingError, match="Field 'modality' must not be empty"):
        parse_riawelc_json({"modality": "   ", "annotations": []}, taxonomy)


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


@pytest.mark.parametrize(
    "bad_point",
    [
        [2],
        [2, 2, 2],
        2,
    ],
)
def test_parse_invalid_point_structure_raises_error(
    taxonomy: TaxonomyConfig, bad_point: object
):
    points = [[1, 1], bad_point, [3, 3], [4, 4]]
    with pytest.raises(
        ParsingError,
        match="point at index 1 must be a list or tuple containing exactly 2 coordinates",
    ):
        parse_riawelc_json(
            {"annotations": [{"label": "porosity", "points": points}]},
            taxonomy,
        )


def test_parse_tuple_points_succeeds(taxonomy: TaxonomyConfig):
    defects = parse_riawelc_json(
        {
            "annotations": [
                {"label": "porosity", "points": [(1, 1), (3, 3), (4, 4)]}
            ]
        },
        taxonomy,
    )
    assert defects[0].polygon.x == (1.0, 3.0, 4.0)
    assert defects[0].polygon.y == (1.0, 3.0, 4.0)


@pytest.mark.parametrize("bad_coordinate", ["1", None, True])
def test_parse_non_numeric_coordinate_raises_error(
    taxonomy: TaxonomyConfig, bad_coordinate: object
):
    with pytest.raises(ParsingError, match="x coordinate at index 0 must be a number"):
        parse_riawelc_json(
            {
                "annotations": [
                    {
                        "label": "porosity",
                        "polygon": {
                            "x": [bad_coordinate, 2, 3],
                            "y": [1, 2, 3],
                        },
                    }
                ]
            },
            taxonomy,
        )


@pytest.mark.parametrize("bad_coordinate", [float("nan"), float("inf"), float("-inf")])
def test_parse_non_finite_coordinate_raises_error(
    taxonomy: TaxonomyConfig, bad_coordinate: float
):
    with pytest.raises(ParsingError, match="x coordinate at index 0 must be finite"):
        parse_riawelc_json(
            {
                "annotations": [
                    {
                        "label": "porosity",
                        "polygon": {
                            "x": [bad_coordinate, 2, 3],
                            "y": [1, 2, 3],
                        },
                    }
                ]
            },
            taxonomy,
        )


def test_parse_oversized_coordinate_raises_parsing_error(taxonomy: TaxonomyConfig):
    with pytest.raises(ParsingError, match="x coordinate at index 0 must be finite"):
        parse_riawelc_json(
            {
                "annotations": [
                    {
                        "label": "porosity",
                        "polygon": {
                            "x": [10**1000, 2, 3],
                            "y": [1, 2, 3],
                        },
                    }
                ]
            },
            taxonomy,
        )


def test_parse_consecutive_duplicate_vertices_raises_error(taxonomy: TaxonomyConfig):
    with pytest.raises(
        ParsingError,
        match="consecutive duplicate vertices at indices 0 and 1",
    ):
        parse_riawelc_json(
            {
                "annotations": [
                    {
                        "label": "porosity",
                        "points": [[1, 1], [1, 1], [3, 1]],
                    }
                ]
            },
            taxonomy,
        )


def test_parse_repeated_closing_vertex_raises_error(taxonomy: TaxonomyConfig):
    with pytest.raises(ParsingError, match="repeats its first vertex at closing index 3"):
        parse_riawelc_json(
            {
                "annotations": [
                    {
                        "label": "porosity",
                        "points": [[1, 1], [3, 1], [2, 3], [1, 1]],
                    }
                ]
            },
            taxonomy,
        )


@pytest.mark.parametrize(
    ("points", "message"),
    [
        ([[-1, 1], [20, 1], [10, 20]], "x coordinate at index 0"),
        ([[1, 1], [101, 1], [10, 20]], "x coordinate at index 1"),
        ([[1, 1], [20, 51], [10, 20]], "y coordinate at index 1"),
    ],
)
def test_parse_out_of_image_bounds_raises_error(
    taxonomy: TaxonomyConfig,
    points: list[list[int]],
    message: str,
):
    with pytest.raises(ParsingError, match=message):
        parse_riawelc_json(
            {
                "image_info": {"width": 100, "height": 50},
                "annotations": [{"label": "porosity", "points": points}],
            },
            taxonomy,
        )


def test_parse_coordinates_on_image_boundary_succeeds(taxonomy: TaxonomyConfig):
    defects = parse_riawelc_json(
        {
            "width": 100,
            "height": 50,
            "annotations": [
                {
                    "label": "porosity",
                    "points": [[0, 0], [100, 0], [50, 50]],
                }
            ],
        },
        taxonomy,
    )
    assert defects[0].polygon.x == (0.0, 100.0, 50.0)
    assert defects[0].polygon.y == (0.0, 0.0, 50.0)


@pytest.mark.parametrize("width", [0, -1, "100", True, float("inf"), 10**1000])
def test_parse_invalid_image_width_raises_error(
    taxonomy: TaxonomyConfig,
    width: object,
):
    with pytest.raises(ParsingError, match="Image width must be a positive finite number"):
        parse_riawelc_json(
            {
                "width": width,
                "annotations": [
                    {
                        "label": "porosity",
                        "points": [[1, 1], [3, 1], [2, 3]],
                    }
                ],
            },
            taxonomy,
        )
