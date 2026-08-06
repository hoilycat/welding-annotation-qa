"""이미지 폴더로 CVAT Task를 생성하거나 같은 구성을 가진 Task를 재사용하는 CLI 모듈."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import sys
from typing import Any

from .cvat_project import (
    CvatIntegrationError,
    CvatSettings,
    connect_cvat,
    ensure_cvat_project,
)
from .models import ParsingError
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
    parser.add_argument("--project-name", help="CVAT project name")
    parser.add_argument("--task-name", help="CVAT task name")
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=Path("configs/taxonomy.yaml"),
        help="Path to the canonical taxonomy YAML",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """설정 로드부터 Project·Task 생성 결과 출력까지 연결하는 CLI 진입점."""
    args = _build_parser().parse_args(argv)
    modality = args.modality.strip().upper()
    project_name = args.project_name or f"Welding QA {modality}"
    task_name = args.task_name or f"{project_name} - {args.images.name}"

    try:
        # taxonomy와 이미지 입력을 먼저 검증한 다음 인증된 SDK client를 생성
        taxonomy = TaxonomyConfig.load_from_yaml(args.taxonomy)
        image_paths = collect_image_paths(args.images)
        settings = CvatSettings.from_environ()
        client = connect_cvat(settings)
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
        finally:
            # 생성·재사용 도중 오류가 나도 SDK의 HTTP session은 항상 정리
            client.close()
    except (CvatIntegrationError, ParsingError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # shell이나 후속 자동화가 생성 여부와 CVAT URL을 읽을 수 있도록 한 줄 JSON으로 출력
    print(
        json.dumps(
            {
                "project_id": _field(project, "id"),
                "project_created": project_created,
                "task_id": _field(task, "id"),
                "task_created": task_created,
                "images": len(image_paths),
                "modality": modality,
                "url": f"{settings.url.rstrip('/')}/tasks/{_field(task, 'id')}",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
