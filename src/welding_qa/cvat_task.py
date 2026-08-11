"""이미지 폴더로 CVAT Task를 생성하거나 같은 구성을 가진 Task를 재사용하는 CLI 모듈."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
import json
from pathlib import Path
import sys
from typing import Any

from .cvat_converter import annotations_to_cvat_shapes, cvat_shapes_to_annotations
from .cvat_project import (
    CvatIntegrationError,
    CvatSettings,
    connect_cvat,
    ensure_cvat_project,
)
from .models import DefectAnnotation, ParsingError
from .riawelc_reader import parse_riawelc_json
from .taxonomy import TaxonomyConfig


# CVAT가 로컬 이미지 resource로 받을 수 있도록 허용하는 파일 확장자 목록
IMAGE_EXTENSIONS = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})


def collect_image_paths(image_root: str | Path) -> list[Path]:
    """폴더 아래의 지원 이미지 파일을 재귀적으로 찾아 안정된 순서로 반환하는 함수."""
    root = Path(image_root)
    if not root.is_dir():
        raise ParsingError(f"Image root must be an existing directory: {root}")

    # 운영체제나 파일 탐색 순서와 무관하게 같은 frame 순서를 만들도록 상대 경로로 정렬
    image_paths = sorted(
        (
            path.resolve()
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ),
        key=lambda path: path.relative_to(root.resolve()).as_posix().lower(),
    )
    if not image_paths:
        raise ParsingError(f"No supported image files found under: {root}")

    # CVAT frame 이름 비교가 모호해지지 않도록 서로 다른 폴더의 같은 파일명을 차단하는 검사
    names = [path.name.casefold() for path in image_paths]
    duplicate_names = sorted(
        name for name, count in Counter(names).items() if count > 1
    )
    if duplicate_names:
        raise ParsingError(
            "Image filenames must be unique across the task: "
            + ", ".join(duplicate_names)
        )
    return image_paths


def build_cvat_task_spec(name: str, project_id: int) -> dict[str, Any]:
    """Project에 연결되는 CVAT Task 생성 payload를 만드는 함수."""
    # 공백 이름과 bool처럼 int로 취급되는 잘못된 project ID를 SDK 호출 전에 차단
    task_name = name.strip() if isinstance(name, str) else ""
    if not task_name:
        raise ParsingError("CVAT task name must be a non-empty string.")
    if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id < 0:
        raise ParsingError("CVAT project ID must be a non-negative integer.")
    return {"name": task_name, "project_id": project_id}


def ensure_cvat_task(
    client: Any,
    project: Any,
    name: str,
    image_paths: Sequence[str | Path],
    *,
    data_params: Mapping[str, Any] | None = None,
) -> tuple[Any, bool]:
    """같은 이름과 frame 구성이면 Task를 재사용하고 없으면 이미지를 업로드하는 함수."""
    normalized_paths = _validate_image_paths(image_paths)
    project_id = _field(project, "id")
    spec = build_cvat_task_spec(name, project_id)

    # 같은 Project 안에서 이름이 같은 Task만 찾아 중복 생성을 막는 멱등 처리
    matching_tasks = [
        task for task in project.get_tasks() if _field(task, "name") == spec["name"]
    ]

    if len(matching_tasks) > 1:
        raise CvatIntegrationError(
            f"Multiple CVAT tasks are named '{spec['name']}'. Rename duplicates first."
        )
    if matching_tasks:
        task = matching_tasks[0]
        # 이름뿐 아니라 정렬된 frame 파일명까지 같아야 동일한 Task로 안전하게 재사용
        expected_names = [path.name for path in normalized_paths]
        actual_names = [
            Path(str(_field(frame, "name"))).name for frame in task.get_frames_info()
        ]
        if actual_names != expected_names:
            raise CvatIntegrationError(
                f"Existing CVAT task '{spec['name']}' has different frames: "
                f"expected {expected_names}, got {actual_names}."
            )
        return task, False

    # 일치하는 Task가 없을 때만 SDK가 로컬 파일을 업로드하며 새 Task를 생성
    resource_type = _get_local_resource_type()
    task = client.tasks.create_from_data(
        spec=spec,
        resources=[str(path) for path in normalized_paths],
        resource_type=resource_type,
        data_params=dict(data_params or {}),
    )
    return task, True


def build_label_id_mappings(project: Any) -> tuple[dict[str, int], dict[int, str]]:
    """CVAT Project의 label 목록에서 canonical_slug <-> label_id 매핑을 추출하는 함수."""
    get_labels_fn = getattr(project, "get_labels", None)
    labels = get_labels_fn() if callable(get_labels_fn) else (_field(project, "labels") or [])
    canonical_to_id: dict[str, int] = {}
    id_to_name: dict[int, str] = {}
    for label in labels:
        label_id = _field(label, "id")
        label_name = _field(label, "name")
        if label_id is not None and label_name:
            canonical_to_id[str(label_name)] = int(label_id)
            id_to_name[int(label_id)] = str(label_name)
    return canonical_to_id, id_to_name


def load_annotations_for_images(
    annotation_root: str | Path,
    image_paths: Sequence[Path],
    taxonomy: TaxonomyConfig,
    *,
    modality: str = "RT",
    allow_missing: bool = False,
) -> dict[str, list[DefectAnnotation]]:
    """이미지 파일 목록과 매칭되는 JSON 어노테이션 파일들을 읽어 지도(dict)로 만드는 함수."""
    root = Path(annotation_root)
    if not root.is_dir():
        raise ParsingError(f"Annotation root must be an existing directory: {root}")

    _validate_unique_stems((path.name for path in image_paths), "Image filenames")

    json_candidates = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".json"),
        key=lambda path: path.relative_to(root).as_posix().casefold(),
    )
    _validate_unique_stems(
        (path.relative_to(root).as_posix() for path in json_candidates),
        "Annotation JSON filenames",
    )
    json_files = {path.stem.casefold(): path for path in json_candidates}

    if not isinstance(modality, str) or not modality.strip():
        raise ParsingError("Annotation modality must be a non-empty string.")
    normalized_modality = modality.strip().upper()
    if not taxonomy.is_known_modality(normalized_modality):
        raise ParsingError(
            f"Annotation modality '{normalized_modality}' is not allowed by canonical taxonomy."
        )

    image_stems = {path.stem.casefold() for path in image_paths}
    unmatched_json_files = [
        path.relative_to(root).as_posix()
        for stem, path in json_files.items()
        if stem not in image_stems
    ]
    if unmatched_json_files:
        raise ParsingError(
            "Annotation JSON files have no matching image: "
            + ", ".join(unmatched_json_files)
        )

    missing_annotation_files = [
        path.name for path in image_paths if path.stem.casefold() not in json_files
    ]
    if missing_annotation_files and not allow_missing:
        raise ParsingError(
            "Images are missing annotation JSON files: "
            + ", ".join(missing_annotation_files)
            + ". Add explicit JSON with annotations: [] for clean images, or use "
            "--allow-missing-annotations."
        )

    annotation_map: dict[str, list[DefectAnnotation]] = {}
    for img_path in image_paths:
        stem_key = img_path.stem.casefold()
        json_path = json_files.get(stem_key)
        if json_path and json_path.is_file():
            annotations = parse_riawelc_json(
                json_path,
                taxonomy,
                default_modality=normalized_modality,
                expected_modality=normalized_modality,
            )
            annotation_map[img_path.name] = annotations
        else:
            annotation_map[img_path.name] = []

    return annotation_map


def sync_task_annotations(
    task: Any,
    project: Any,
    annotation_map: Mapping[str, Sequence[DefectAnnotation]],
    *,
    replace_existing: bool = False,
) -> int:
    """Task frame에 맞춘 shape를 설정하며 기존 작업 결과는 명시적 요청 없이 보존한다."""
    canonical_to_id, _ = build_label_id_mappings(project)
    get_frames_fn = getattr(task, "get_frames_info", None)
    frames_info = get_frames_fn() if callable(get_frames_fn) else (_field(task, "frames") or [])
    frame_names = [Path(str(_field(frame, "name"))).name for frame in frames_info]
    expected_frame_names = set(frame_names)
    provided_frame_names = set(annotation_map)
    if expected_frame_names != provided_frame_names:
        missing = sorted(expected_frame_names - provided_frame_names)
        unexpected = sorted(provided_frame_names - expected_frame_names)
        details = []
        if missing:
            details.append("missing frames: " + ", ".join(missing))
        if unexpected:
            details.append("unknown frames: " + ", ".join(unexpected))
        raise ParsingError("Annotation map does not match CVAT task frames (" + "; ".join(details) + ").")

    all_shapes: list[dict[str, Any]] = []
    for frame_idx, frame_name in enumerate(frame_names):
        annotations = annotation_map[frame_name]
        if annotations:
            shapes = annotations_to_cvat_shapes(annotations, canonical_to_id, frame=frame_idx)
            all_shapes.extend(shapes)

    existing_payload = _get_task_annotations(task)
    if any(existing_payload.get(field) for field in ("shapes", "tracks", "tags")) and not replace_existing:
        raise CvatIntegrationError(
            "CVAT task already has annotations. Create a native CVAT dataset backup first, "
            "then rerun with --replace-annotations to replace them explicitly."
        )

    payload = {"shapes": all_shapes, "tracks": [], "tags": []}
    if hasattr(task, "set_annotations") and callable(task.set_annotations):
        task.set_annotations(_build_annotation_request(task, payload))
    elif hasattr(task, "put_annotations") and callable(task.put_annotations):
        task.put_annotations(payload)
    else:
        if isinstance(task, dict):
            task["annotations"] = payload
        else:
            setattr(task, "annotations", payload)

    return len(all_shapes)


def export_task_annotations(
    task: Any,
    project: Any,
    taxonomy: TaxonomyConfig,
    *,
    modality: str = "RT",
) -> dict[str, list[DefectAnnotation]]:
    """CVAT Task의 polygon shape를 읽어 이미지 파일명별 DefectAnnotation으로 내보내는 함수."""
    _, id_to_name = build_label_id_mappings(project)
    get_frames_fn = getattr(task, "get_frames_info", None)
    frames_info = get_frames_fn() if callable(get_frames_fn) else (_field(task, "frames") or [])

    annotation_payload = _get_task_annotations(task)
    unsupported_fields = [
        field for field in ("tracks", "tags") if annotation_payload[field]
    ]
    if unsupported_fields:
        raise CvatIntegrationError(
            "Canonical polygon export cannot preserve CVAT "
            + " and ".join(unsupported_fields)
            + ". Use CVAT's native dataset export for a complete backup."
        )
    shapes = annotation_payload["shapes"]

    shapes_by_frame: dict[int, list[dict[str, Any]]] = {}
    for shape_index, shape in enumerate(shapes):
        shape_dict = shape if isinstance(shape, dict) else {
            "type": getattr(_field(shape, "type"), "value", _field(shape, "type")),
            "frame": _field(shape, "frame"),
            "label_id": _field(shape, "label_id"),
            "points": list(_field(shape, "points") or []),
            "group": _field(shape, "group") or 0,
            "source": _field(shape, "source") or "manual",
        }
        frame_idx = shape_dict.get("frame", 0)
        if (
            isinstance(frame_idx, bool)
            or not isinstance(frame_idx, int)
            or not 0 <= frame_idx < len(frames_info)
        ):
            raise ParsingError(
                f"CVAT shape at index {shape_index} references invalid frame "
                f"'{frame_idx}' for a task with {len(frames_info)} frames."
            )
        shapes_by_frame.setdefault(frame_idx, []).append(shape_dict)

    frame_names = [Path(str(_field(frame, "name"))).name for frame in frames_info]
    _validate_unique_stems(frame_names, "CVAT frame filenames")

    result: dict[str, list[DefectAnnotation]] = {}
    for frame_idx, frame in enumerate(frames_info):
        frame_name = Path(str(_field(frame, "name"))).name
        frame_shapes = shapes_by_frame.get(frame_idx, [])
        if frame_shapes:
            result[frame_name] = cvat_shapes_to_annotations(
                frame_shapes, id_to_name, taxonomy, modality=modality
            )
        else:
            result[frame_name] = []

    return result


def _get_task_annotations(task: Any) -> dict[str, list[Any]]:
    """실제 SDK 객체와 테스트 대역에서 annotation payload를 같은 형태로 읽는다."""
    if hasattr(task, "get_annotations") and callable(task.get_annotations):
        raw_annotations = task.get_annotations()
    else:
        raw_annotations = _field(task, "annotations") or {}

    return {
        field: list(_field(raw_annotations, field) or [])
        for field in ("shapes", "tracks", "tags")
    }


def _build_annotation_request(task: Any, payload: Mapping[str, Sequence[Any]]) -> Any:
    """실제 CVAT SDK proxy에는 생성 모델을, 테스트 대역에는 dict를 전달한다."""
    if not type(task).__module__.startswith("cvat_sdk."):
        return dict(payload)

    try:
        from cvat_sdk import models
    except ImportError as exc:
        raise CvatIntegrationError(
            'CVAT SDK is not installed. Run: pip install -e ".[dev,cvat]"'
        ) from exc

    return models.LabeledDataRequest(
        shapes=[models.LabeledShapeRequest(**shape) for shape in payload["shapes"]],
        tracks=[],
        tags=[],
    )


def _validate_unique_stems(names: Iterable[str], description: str) -> None:
    """stem 기반 JSON 매칭·출력에서 조용한 충돌과 덮어쓰기를 방지한다."""
    stems = [Path(name).stem.casefold() for name in names]
    duplicate_stems = sorted(stem for stem, count in Counter(stems).items() if count > 1)
    if duplicate_stems:
        raise ParsingError(
            f"{description} must have unique stems for annotation matching: "
            + ", ".join(duplicate_stems)
        )


def _validate_image_paths(image_paths: Sequence[str | Path]) -> tuple[Path, ...]:
    """직접 전달된 이미지 경로도 수집 함수와 같은 규칙으로 검증하는 함수."""
    if isinstance(image_paths, (str, bytes)) or not isinstance(image_paths, Sequence):
        raise ParsingError("CVAT task image paths must be a sequence of file paths.")
    if not image_paths:
        raise ParsingError("CVAT task requires at least one image file.")

    # SDK에 넘기기 전에 각 경로의 타입, 존재 여부와 지원 확장자를 순서대로 검증
    normalized = []
    for index, value in enumerate(image_paths):
        if not isinstance(value, (str, Path)):
            raise ParsingError(
                f"Image path at index {index} must be a string or Path."
            )
        path = Path(value)
        if not path.is_file():
            raise ParsingError(f"Image path at index {index} is not a file: {path}")
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ParsingError(f"Image path at index {index} has an unsupported extension: {path}")
        normalized.append(path.resolve())

    # CVAT frame 비교는 basename을 사용하므로 대소문자만 다른 중복 이름도 허용하지 않음
    names = [path.name.casefold() for path in normalized]
    if len(names) != len(set(names)):
        raise ParsingError("CVAT task image filenames must be unique.")
    return tuple(normalized)


def _get_local_resource_type() -> Any:
    """기본 설치에서 cvat-sdk를 필수로 만들지 않도록 ResourceType을 지연 import하는 함수."""
    try:
        from cvat_sdk.core.proxies.tasks import ResourceType
    except ImportError as exc:
        raise CvatIntegrationError(
            'CVAT SDK is not installed. Run: pip install -e ".[dev,cvat]"'
        ) from exc
    return ResourceType.LOCAL


def _field(value: Any, name: str) -> Any:
    """테스트 dictionary와 실제 CVAT SDK 객체의 필드를 같은 방식으로 읽는 함수."""
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _build_parser() -> argparse.ArgumentParser:
    """CVAT Task 업로드 CLI가 지원하는 명령행 인자를 구성하는 함수."""
    # 자동화와 수동 실행 모두에서 Project·Task 이름을 필요할 때 덮어쓸 수 있는 CLI 인자
    parser = argparse.ArgumentParser(
        description="Create or reuse a CVAT task and upload a local image directory."
    )
    parser.add_argument("--modality", required=True, help="Task modality, such as RT or VT")
    parser.add_argument("--images", required=True, type=Path, help="Image directory to upload")
    parser.add_argument("--annotations", type=Path, help="Directory containing JSON annotations to upload")
    parser.add_argument(
        "--allow-missing-annotations",
        action="store_true",
        help="Treat images without matching JSON files as empty annotations",
    )
    parser.add_argument("--export-annotations", type=Path, help="Directory to save exported CVAT annotations")
    parser.add_argument(
        "--replace-annotations",
        action="store_true",
        help="Replace all existing task annotations when used with --annotations",
    )
    parser.add_argument("--project-name", help="CVAT project name")
    parser.add_argument("--task-name", help="CVAT task name")
    parser.add_argument(
        "--taxonomy",
        type=Path,
        help="Path to a custom taxonomy YAML (defaults to packaged canonical taxonomy)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """설정 로드부터 Project·Task 생성 및 어노테이션 동기화 결과 출력까지 연결하는 CLI 진입점."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.replace_annotations and not args.annotations:
        parser.error("--replace-annotations requires --annotations")
    if args.allow_missing_annotations and not args.annotations:
        parser.error("--allow-missing-annotations requires --annotations")
    modality = args.modality.strip().upper()
    project_name = args.project_name or f"Welding QA {modality}"
    task_name = args.task_name or f"{project_name} - {args.images.name}"

    try:
        # taxonomy와 이미지 입력을 먼저 검증한 다음 인증된 SDK client를 생성
        taxonomy = (
            TaxonomyConfig.load_from_yaml(args.taxonomy)
            if args.taxonomy
            else TaxonomyConfig.load_default()
        )
        image_paths = collect_image_paths(args.images)
        annotation_map = None
        if args.annotations:
            annotation_map = load_annotations_for_images(
                args.annotations,
                image_paths,
                taxonomy,
                modality=modality,
                allow_missing=args.allow_missing_annotations,
            )
        settings = CvatSettings.from_environ()
        client = connect_cvat(settings)
        synced_shapes_count = 0
        exported_files_count = 0
        try:
            # 상위 Project를 먼저 보장한 뒤 그 안에서 Task 생성 또는 재사용을 수행
            project, project_created = ensure_cvat_project(
                client,
                project_name,
                taxonomy,
                modality,
            )
            task, task_created = ensure_cvat_task(
                client,
                project,
                task_name,
                image_paths,
            )

            if annotation_map is not None:
                synced_shapes_count = sync_task_annotations(
                    task,
                    project,
                    annotation_map,
                    replace_existing=args.replace_annotations,
                )

            if args.export_annotations:
                exported_ann = export_task_annotations(
                    task, project, taxonomy, modality=modality
                )
                out_dir = Path(args.export_annotations)
                out_dir.mkdir(parents=True, exist_ok=True)
                for img_name, annotations in exported_ann.items():
                    out_file = out_dir / f"{Path(img_name).stem}.json"
                    export_data = {
                        "filename": img_name,
                        "modality": modality,
                        "annotations": [
                            {
                                "label": ann.label_original,
                                "canonical_label": ann.label_canonical,
                                "points": [[x, y] for x, y in zip(ann.polygon.x, ann.polygon.y)],
                            }
                            for ann in annotations
                        ],
                    }
                    out_file.write_text(json.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    exported_files_count += 1
        finally:
            # 생성·재사용 도중 오류가 나도 SDK의 HTTP session은 항상 정리
            client.close()
    except (CvatIntegrationError, ParsingError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # shell이나 후속 자동화가 생성 여부와 CVAT URL을 읽을 수 있도록 한 줄 JSON으로 출력
    result_payload: dict[str, Any] = {
        "project_id": _field(project, "id"),
        "project_created": project_created,
        "task_id": _field(task, "id"),
        "task_created": task_created,
        "images": len(image_paths),
        "modality": modality,
        "url": f"{settings.url.rstrip('/')}/tasks/{_field(task, 'id')}",
    }
    if args.annotations:
        result_payload["synced_shapes"] = synced_shapes_count
    if args.export_annotations:
        result_payload["exported_files"] = exported_files_count

    print(json.dumps(result_payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
