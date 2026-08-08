"""RIAWELC 계열 JSON 입력을 내부 DefectAnnotation 목록으로 변환하는 모듈."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import DefectAnnotation, ParsingError, Polygon, validate_image_dimensions
from .taxonomy import TaxonomyConfig


def parse_riawelc_json(
    json_path_or_content: str | Path | dict[str, Any],
    taxonomy: TaxonomyConfig,
    default_modality: str = "RT",
    *,
    expected_modality: str | None = None,
) -> list[DefectAnnotation]:
    """파일 경로, JSON 문자열, dictionary 입력을 검증된 annotation 목록으로 바꾸는 함수."""
    # 문자열이 실제 파일 경로인지 먼저 확인하고 아니면 JSON 본문으로 처리하는 입력 분기
    if isinstance(json_path_or_content, (str, Path)) and (
        isinstance(json_path_or_content, Path) or Path(json_path_or_content).is_file()
    ):
        path = Path(json_path_or_content)
        try:
            # Windows 도구가 추가하는 UTF-8 BOM도 투명하게 제거해 JSON을 읽는다.
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ParsingError(f"Invalid JSON in file '{path}': {exc.msg}") from exc
    elif isinstance(json_path_or_content, str):
        try:
            data = json.loads(json_path_or_content)
        except json.JSONDecodeError as exc:
            raise ParsingError(f"Invalid JSON content: {exc.msg}") from exc
    elif isinstance(json_path_or_content, dict):
        data = json_path_or_content
    else:
        raise ParsingError(f"Invalid JSON input type: {type(json_path_or_content)}")

    if not isinstance(data, dict):
        raise ParsingError("Root JSON structure must be a dictionary object.")

    # 데이터셋 버전별로 다른 annotation 목록 필드 이름을 순서대로 지원하는 코드
    annotations_field = None
    for candidate in ("annotations", "shapes", "objects"):
        if candidate in data:
            annotations_field = candidate
            break
    if annotations_field is None:
        raise ParsingError("JSON missing required 'annotations', 'shapes', or 'objects' list field.")
    annotations_list = data[annotations_field]
    if not isinstance(annotations_list, list):
        raise ParsingError(f"Field '{annotations_field}' must be a list.")

    source_info = data.get("info", {})
    if not isinstance(source_info, dict):
        raise ParsingError("Field 'info' must be a dictionary object.")

    # 정규화 스키마의 modality와 실제 RIAWELC info.type을 모두 지원한다.
    modality = data.get("modality", source_info.get("type", default_modality))
    if not isinstance(modality, str):
        raise ParsingError("Field 'modality' must be a string.")
    if not modality.strip():
        raise ParsingError("Field 'modality' must not be empty.")
    modality = modality.strip().upper()
    if not taxonomy.is_known_modality(modality):
        raise ParsingError(
            f"Field modality '{modality}' is not allowed by canonical taxonomy."
        )

    if expected_modality is not None:
        if not isinstance(expected_modality, str) or not expected_modality.strip():
            raise ParsingError("Expected modality must be a non-empty string.")
        normalized_expected_modality = expected_modality.strip().upper()
        if modality != normalized_expected_modality:
            raise ParsingError(
                f"JSON modality '{modality}' does not match expected modality "
                f"'{normalized_expected_modality}'."
            )

    source_image_data = data.get("image_data", {})
    if not isinstance(source_image_data, dict):
        raise ParsingError("Field 'image_data' must be a dictionary object.")

    # 정규화 image_info를 우선하되 실제 RIAWELC image_data와 구형 최상위 필드도 지원한다.
    image_info = data.get("image_info", {})
    if not isinstance(image_info, dict):
        raise ParsingError("Field 'image_info' must be a dictionary object.")
    image_width = image_info.get(
        "width", source_image_data.get("width", data.get("width"))
    )
    image_height = image_info.get(
        "height", source_image_data.get("height", data.get("height"))
    )
    image_filename = image_info.get("filename", data.get("filename"))
    if image_filename is None and source_image_data.get("file_name"):
        image_filename = str(source_image_data["file_name"])
        image_format = source_image_data.get("format")
        if image_format and not Path(image_filename).suffix:
            image_filename = f"{image_filename}.{str(image_format).lstrip('.')}"
    image_id = image_info.get(
        "image_id", data.get("image_id", source_info.get("id"))
    )
    # annotation이 0개여도 잘못된 이미지 크기를 놓치지 않게 반복문 전에 실행하는 검사
    validate_image_dimensions(width=image_width, height=image_height)

    parsed_defects: list[DefectAnnotation] = []

    # 한 항목이라도 잘못되면 일부 결과를 반환하지 않고 파일 전체를 거부하는 처리
    for idx, item in enumerate(annotations_list):
        if not isinstance(item, dict):
            raise ParsingError(f"Annotation item at index {idx} must be a dictionary object.")

        raw_label = (
            item.get("label")
            or item.get("class_name")
            or item.get("defect_type")
            or item.get("case")
        )
        if not raw_label:
            raise ParsingError(f"Annotation item at index {idx} missing label field.")

        # 원본 라벨을 taxonomy의 canonical slug로 통일하고 modality 정책까지 확인하는 코드
        try:
            canonical_slug = taxonomy.get_canonical_slug(str(raw_label))
        except ValueError as exc:
            raise ParsingError(
                f"Annotation item at index {idx} has invalid label: {exc}"
            ) from exc
        if not taxonomy.is_modality_allowed(canonical_slug, modality):
            raise ParsingError(
                f"Annotation item at index {idx}: modality '{modality}' is not allowed "
                f"for canonical label '{canonical_slug}'."
            )

        # polygon.x/y, points[[x,y]], 항목 직속 x/y 형식을 모두 받는 호환 처리
        if "polygon" in item:
            poly_data = item["polygon"]
        elif "coordinate" in item:
            poly_data = item["coordinate"]
        elif "points" in item:
            poly_data = item["points"]
        else:
            poly_data = item

        if isinstance(poly_data, dict):
            xs = poly_data.get("x") if "x" in poly_data else poly_data.get("xs")
            ys = poly_data.get("y") if "y" in poly_data else poly_data.get("ys")
        elif isinstance(poly_data, (list, tuple)):
            xs = []
            ys = []
            for point_idx, point in enumerate(poly_data):
                # 잘못된 point를 조용히 제거하지 않고 annotation 전체를 거부하는 검사
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    raise ParsingError(
                        f"Annotation item at index {idx}, point at index {point_idx} "
                        "must be a list or tuple containing exactly 2 coordinates."
                    )
                xs.append(point[0])
                ys.append(point[1])
        else:
            xs, ys = None, None

        if xs is None or ys is None:
            raise ParsingError(f"Annotation item at index {idx} missing 'x' and 'y' polygon coordinates.")

        # 문자열처럼 순회 가능한 값이 좌표 목록으로 잘못 통과하지 않도록 타입을 제한
        if not isinstance(xs, (list, tuple)) or not isinstance(ys, (list, tuple)):
            raise ParsingError(
                f"Annotation item at index {idx} polygon fields 'x' and 'y' must be lists or tuples."
            )

        if len(xs) != len(ys):
            raise ParsingError(
                f"Annotation item at index {idx}: x and y coordinate lengths mismatch: "
                f"len(x)={len(xs)}, len(y)={len(ys)}"
            )

        # Polygon 모델의 숫자·중복점 검사와 이미지 경계 검사를 한곳에서 감싸는 코드
        try:
            polygon = Polygon(x=tuple(xs), y=tuple(ys))
            polygon.validate_image_bounds(width=image_width, height=image_height)
        except ParsingError as exc:
            raise ParsingError(f"Annotation item at index {idx}: {exc}") from exc

        # 학습 전후 추적에 필요한 원본 이미지 메타데이터를 그대로 보존하는 코드
        parsed_defects.append(
            DefectAnnotation(
                label_original=str(raw_label),
                label_canonical=canonical_slug,
                polygon=polygon,
                modality=modality,
                extra_meta={
                    "image_id": image_id,
                    "filename": image_filename,
                    "width": image_width,
                    "height": image_height,
                },
            )
        )

    return parsed_defects
