import pytest

from welding_qa.cvat_converter import polygon_from_cvat_points
from welding_qa.models import ParsingError, Polygon
from welding_qa.riawelc_reader import parse_riawelc_json
from welding_qa.taxonomy import TaxonomyConfig


@pytest.fixture
def taxonomy() -> TaxonomyConfig:
    return TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")


@pytest.mark.parametrize(
    ("points", "message"),
    [
        ([(0, 0), (1, 1), (2, 2)], "area is zero or too small"),
        ([(0, 0), (1, 1), (2, 2), (3, 3)], "area is zero or too small"),
        ([(0, 0), (1, 0), (1, 1e-14)], "area is zero or too small"),
    ],
)
def test_polygon_rejects_zero_or_nearly_zero_area(
    points: list[tuple[float, float]],
    message: str,
):
    with pytest.raises(ParsingError, match=message):
        Polygon(
            x=tuple(point[0] for point in points),
            y=tuple(point[1] for point in points),
        )


@pytest.mark.parametrize(
    "points",
    [
        [(0, 0), (2, 2), (0, 2), (2, 0)],
        [(0, 0), (2, 0), (2, 2), (1, 0), (0, 2)],
        [(0, 0), (4, 0), (4, 2), (1, 0), (3, 0), (0, 2)],
    ],
)
def test_polygon_rejects_non_adjacent_edge_intersections(
    points: list[tuple[int, int]],
):
    with pytest.raises(ParsingError, match="self-intersection"):
        Polygon(
            x=tuple(point[0] for point in points),
            y=tuple(point[1] for point in points),
        )


@pytest.mark.parametrize(
    "points",
    [
        [(0, 0), (3, 0), (1, 2)],
        [(0, 0), (3, 0), (3, 2), (0, 2)],
        [(0, 0), (4, 0), (4, 4), (2, 2), (0, 4)],
    ],
)
def test_polygon_accepts_simple_convex_and_concave_shapes(
    points: list[tuple[int, int]],
):
    polygon = Polygon(
        x=tuple(point[0] for point in points),
        y=tuple(point[1] for point in points),
    )
    assert len(polygon.x) == len(points)


def test_polygon_accepts_clockwise_and_counterclockwise_order():
    counterclockwise = [(0, 0), (3, 0), (1, 2)]
    clockwise = list(reversed(counterclockwise))

    for points in (counterclockwise, clockwise):
        polygon = Polygon(
            x=tuple(point[0] for point in points),
            y=tuple(point[1] for point in points),
        )
        assert len(polygon.x) == 3


def test_polygon_accepts_valid_small_scale_floating_point_shape():
    polygon = Polygon(
        x=(0.0, 1e-9, 0.0),
        y=(0.0, 0.0, 1e-9),
    )
    assert polygon.x == (0.0, 1e-9, 0.0)


def test_polygon_handles_large_finite_coordinates_without_overflow():
    polygon = Polygon(
        x=(1e308, 9e307, 9e307),
        y=(1e308, 1e308, 9e307),
    )
    assert len(polygon.x) == 3


def test_riawelc_parser_adds_annotation_index_to_validity_error(
    taxonomy: TaxonomyConfig,
):
    with pytest.raises(
        ParsingError,
        match="Annotation item at index 0: Polygon has self-intersection",
    ):
        parse_riawelc_json(
            {
                "annotations": [
                    {
                        "label": "porosity",
                        "points": [[0, 0], [2, 2], [0, 2], [2, 0]],
                    }
                ]
            },
            taxonomy,
        )


def test_cvat_polygon_conversion_applies_validity_validation():
    with pytest.raises(ParsingError, match="self-intersection"):
        polygon_from_cvat_points([0, 0, 2, 2, 0, 2, 2, 0])
