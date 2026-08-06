"""외부 사용자가 안정적으로 import할 공개 API를 한곳에 모으는 패키지 진입점."""

from .cvat_converter import (
    annotation_to_cvat_shape,
    annotations_to_cvat_shapes,
    cvat_shape_to_annotation,
    cvat_shapes_to_annotations,
    polygon_from_cvat_points,
    polygon_to_cvat_points,
)
from .models import DefectAnnotation, ParsingError, Polygon
from .riawelc_reader import parse_riawelc_json
from .taxonomy import TaxonomyConfig

# 내부 헬퍼는 숨기고 모델·파서·CVAT 변환 함수만 공개하는 목록
__all__ = [
    "Polygon",
    "DefectAnnotation",
    "ParsingError",
    "TaxonomyConfig",
    "parse_riawelc_json",
    "polygon_to_cvat_points",
    "polygon_from_cvat_points",
    "annotation_to_cvat_shape",
    "annotations_to_cvat_shapes",
    "cvat_shape_to_annotation",
    "cvat_shapes_to_annotations",
    "collect_image_paths",
    "ensure_cvat_task",
]


def __getattr__(name: str) -> object:
    """CVAT Task API를 요청할 때만 모듈을 불러와 CLI 선행 import를 피하는 함수."""
    if name in {"collect_image_paths", "ensure_cvat_task"}:
        from importlib import import_module

        cvat_task = import_module(".cvat_task", __name__)
        return getattr(cvat_task, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
