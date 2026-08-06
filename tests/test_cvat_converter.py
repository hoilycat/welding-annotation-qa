from pathlib import Path

import pytest

from welding_qa.cvat_converter import (
    annotation_to_cvat_shape,
    annotations_to_cvat_shapes,
    cvat_shape_to_annotation,
    cvat_shapes_to_annotations,
    polygon_from_cvat_points,
    polygon_to_cvat_points,
)
from welding_qa.models import DefectAnnotation, ParsingError, Polygon
from welding_qa.taxonomy import TaxonomyConfig


@pytest.fixture
def taxonomy() -> TaxonomyConfig:
    yaml_path = Path(__file__).resolve().parents[1] / "configs" / "taxonomy.yaml"
    return TaxonomyConfig.load_from_yaml(yaml_path)


@pytest.fixture
def annotation() -> DefectAnnotation:
    return DefectAnnotation(
        label_original="gas_pore",
        label_canonical="porosity",
        polygon=Polygon(x=(10, 30, 20), y=(20, 20, 40)),
        modality="RT",
    )


def test_polygon_to_cvat_points_flattens_xy_pairs(annotation: DefectAnnotation):
    assert polygon_to_cvat_points(annotation.polygon) == [
        10.0,
        20.0,
        30.0,
        20.0,
        20.0,
        40.0,
    ]


def test_polygon_from_cvat_points_restores_xy_coordinates():
    polygon = polygon_from_cvat_points([10, 20, 30, 20, 20, 40])
    assert polygon.x == (10.0, 30.0, 20.0)
    assert polygon.y == (20.0, 20.0, 40.0)


def test_annotation_to_cvat_shape_builds_labeled_shape_request(
    annotation: DefectAnnotation,
):
    shape = annotation_to_cvat_shape(annotation, label_id=7, frame=3)
    assert shape == {
        "type": "polygon",
        "frame": 3,
        "label_id": 7,
        "points": [10.0, 20.0, 30.0, 20.0, 20.0, 40.0],
        "occluded": False,
        "outside": False,
        "z_order": 0,
        "rotation": 0.0,
        "group": 0,
        "source": "manual",
        "attributes": [],
    }


def test_annotations_to_cvat_shapes_uses_canonical_label_mapping(
    annotation: DefectAnnotation,
):
    shapes = annotations_to_cvat_shapes(
        [annotation],
        {"porosity": 7},
        frame=3,
    )
    assert shapes[0]["label_id"] == 7
    assert shapes[0]["frame"] == 3


def test_cvat_shape_to_annotation_normalizes_label_and_preserves_metadata(
    taxonomy: TaxonomyConfig,
):
    shape = {
        "id": 99,
        "type": "polygon",
        "frame": 3,
        "label_id": 7,
        "points": [10, 20, 30, 20, 20, 40],
        "source": "manual",
        "occluded": True,
    }
    annotation = cvat_shape_to_annotation(
        shape,
        {7: "gas_pore"},
        taxonomy,
        modality="RT",
    )

    assert annotation.label_original == "gas_pore"
    assert annotation.label_canonical == "porosity"
    assert annotation.polygon.x == (10.0, 30.0, 20.0)
    assert annotation.polygon.y == (20.0, 20.0, 40.0)
    assert annotation.modality == "RT"
    assert annotation.extra_meta == {
        "cvat": {
            "id": 99,
            "frame": 3,
            "label_id": 7,
            "source": "manual",
            "occluded": True,
        }
    }


def test_cvat_round_trip_preserves_core_annotation_fields(
    annotation: DefectAnnotation,
    taxonomy: TaxonomyConfig,
):
    shape = annotation_to_cvat_shape(annotation, label_id=7, frame=3)
    restored = cvat_shape_to_annotation(
        shape,
        {7: "porosity"},
        taxonomy,
        modality=annotation.modality,
    )

    assert restored.label_canonical == annotation.label_canonical
    assert restored.polygon == annotation.polygon
    assert restored.modality == annotation.modality


@pytest.mark.parametrize(
    ("points", "message"),
    [
        ([1, 2, 3, 4, 5], "must contain x/y pairs"),
        ([1, 2, 3, 4], "requires at least 3 vertices"),
        ("1,2,3,4,5,6", "must be a list or tuple"),
    ],
)
def test_polygon_from_cvat_points_rejects_invalid_structure(
    points: object,
    message: str,
):
    with pytest.raises(ParsingError, match=message):
        polygon_from_cvat_points(points)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["label_id", "frame"])
def test_annotation_to_cvat_shape_rejects_invalid_integer_fields(
    annotation: DefectAnnotation,
    field: str,
):
    kwargs = {"label_id": 7, "frame": 0}
    kwargs[field] = False
    with pytest.raises(ParsingError, match=field):
        annotation_to_cvat_shape(annotation, **kwargs)


def test_annotations_to_cvat_shapes_requires_label_mapping(
    annotation: DefectAnnotation,
):
    with pytest.raises(
        ParsingError,
        match="no CVAT label ID configured for canonical label 'porosity'",
    ):
        annotations_to_cvat_shapes([annotation], {})


def test_cvat_shape_to_annotation_rejects_non_polygon(
    taxonomy: TaxonomyConfig,
):
    with pytest.raises(ParsingError, match="field 'type' must be 'polygon'"):
        cvat_shape_to_annotation(
            {
                "type": "rectangle",
                "frame": 0,
                "label_id": 7,
                "points": [1, 2, 3, 4],
            },
            {7: "porosity"},
            taxonomy,
        )


def test_cvat_shape_to_annotation_rejects_unknown_label_id(
    taxonomy: TaxonomyConfig,
):
    with pytest.raises(ParsingError, match="Unknown CVAT label ID '999'"):
        cvat_shape_to_annotation(
            {
                "type": "polygon",
                "frame": 0,
                "label_id": 999,
                "points": [1, 2, 3, 4, 5, 6],
            },
            {7: "porosity"},
            taxonomy,
        )


def test_cvat_shapes_to_annotations_adds_shape_index_to_errors(
    taxonomy: TaxonomyConfig,
):
    with pytest.raises(ParsingError, match="CVAT shape at index 1"):
        cvat_shapes_to_annotations(
            [
                {
                    "type": "polygon",
                    "frame": 0,
                    "label_id": 7,
                    "points": [1, 2, 4, 2, 2, 5],
                },
                {
                    "type": "polygon",
                    "frame": 1,
                    "label_id": 999,
                    "points": [1, 2, 3, 4, 5, 6],
                },
            ],
            {7: "porosity"},
            taxonomy,
        )
