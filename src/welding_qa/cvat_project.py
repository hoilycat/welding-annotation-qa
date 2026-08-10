"""Canonical taxonomy로 CVAT Project를 생성하거나 기존 Project를 재사용하는 CLI 모듈."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any

from .models import ParsingError
from .taxonomy import TaxonomyConfig


# taxonomy 순서를 시각적으로 구분하기 위해 순환해서 사용하는 기본 label 색상
_LABEL_COLORS = (
    "#E76F51",
    "#F4A261",
    "#E9C46A",
    "#2A9D8F",
    "#457B9D",
    "#6D597A",
)


class CvatIntegrationError(RuntimeError):
    """CVAT SDK 연결·인증·Project 상태가 기대와 다를 때 사용하는 예외."""


@dataclass(frozen=True)
class CvatSettings:
    """환경변수에서 읽은 CVAT 접속 정보만 보관하는 설정 모델."""

    url: str
    username: str | None = None
    password: str | None = None
    access_token: str | None = None

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> CvatSettings:
        """환경변수에서 URL과 PAT 또는 계정 인증정보를 검증해 읽는 함수."""
        # PAT가 있으면 계정 비밀번호보다 우선해서 사용하는 인증 정책
        values = os.environ if environ is None else environ
        url = values.get("CVAT_URL", "http://localhost:8080").strip()
        username = values.get("CVAT_USERNAME", "").strip() or None
        password = values.get("CVAT_PASSWORD") or None
        access_token = values.get("CVAT_ACCESS_TOKEN") or None

        if not url:
            raise CvatIntegrationError("CVAT_URL must not be empty.")
        if access_token:
            return cls(url=url, access_token=access_token)
        if not username or not password:
            raise CvatIntegrationError(
                "Set CVAT_ACCESS_TOKEN or both CVAT_USERNAME and CVAT_PASSWORD."
            )
        return cls(url=url, username=username, password=password)


def connect_cvat(settings: CvatSettings) -> Any:
    """인증과 서버 버전 확인을 마친 CVAT SDK client를 만드는 함수."""
    # cvat 기능을 사용하지 않는 설치에서는 SDK가 필수가 아니도록 지연 import하는 코드
    try:
        from cvat_sdk import make_client
    except ImportError as exc:
        raise CvatIntegrationError(
            'CVAT SDK is not installed. Run: pip install -e ".[dev,cvat]"'
        ) from exc

    # 네트워크·인증·버전 오류를 CLI가 한 종류로 안내할 수 있게 감싸는 외부 SDK 경계
    try:
        if settings.access_token:
            client = make_client(settings.url, access_token=settings.access_token)
        else:
            client = make_client(
                settings.url,
                credentials=(settings.username or "", settings.password or ""),
            )
        client.check_server_version(fail_if_unsupported=True)
        return client
    except Exception as exc:
        raise CvatIntegrationError(f"Could not connect to CVAT at {settings.url}: {exc}") from exc


def build_cvat_project_spec(
    name: str,
    taxonomy: TaxonomyConfig,
    modality: str,
) -> dict[str, Any]:
    """해당 modality에 허용된 canonical label로 CVAT Project payload를 만드는 함수."""
    # SDK에 잘못된 Project 이름이나 modality가 전달되기 전에 사용자 입력을 정규화
    project_name = name.strip() if isinstance(name, str) else ""
    if not project_name:
        raise ParsingError("CVAT project name must be a non-empty string.")
    if not isinstance(modality, str) or not modality.strip():
        raise ParsingError("CVAT project modality must be a non-empty string.")

    normalized_modality = modality.strip().upper()
    # YAML 순서를 그대로 유지해 Project label 표시 순서와 색상을 안정적으로 만드는 코드
    labels = []
    for index, canonical_slug in enumerate(taxonomy.canonical_classes):
        if taxonomy.is_modality_allowed(canonical_slug, normalized_modality):
            labels.append(
                {
                    "name": canonical_slug,
                    "color": _LABEL_COLORS[index % len(_LABEL_COLORS)],
                    "type": "polygon",
                    "attributes": [],
                }
            )

    if not labels:
        raise ParsingError(
            f"No canonical labels are configured for modality '{normalized_modality}'."
        )

    return {"name": project_name, "labels": labels}


def ensure_cvat_project(
    client: Any,
    name: str,
    taxonomy: TaxonomyConfig,
    modality: str,
) -> tuple[Any, bool]:
    """같은 Project가 있으면 검증 후 재사용하고 없으면 새로 만드는 함수."""
    spec = build_cvat_project_spec(name, taxonomy, modality)
    # 이름이 같은 Project 전체를 찾아 중복 생성을 막는 idempotent 처리
    matching_projects = [
        project
        for project in client.projects.list()
        if _field(project, "name") == spec["name"]
    ]

    if len(matching_projects) > 1:
        raise CvatIntegrationError(
            f"Multiple CVAT projects are named '{spec['name']}'. Rename duplicates first."
        )
    if matching_projects:
        project = matching_projects[0]
        # label 이름과 shape type이 정확히 같은 경우에만 안전한 재사용으로 판단하는 코드
        expected_labels = {
            label["name"]: label["type"] for label in spec["labels"]
        }
        actual_labels = {
            _field(label, "name"): _enum_value(_field(label, "type"))
            for label in project.get_labels()
        }
        if actual_labels != expected_labels:
            raise CvatIntegrationError(
                f"Existing CVAT project '{spec['name']}' has different labels: "
                f"expected {expected_labels}, got {actual_labels}."
            )
        return project, False

    # 같은 이름의 Project가 없을 때만 taxonomy label 전체를 포함해 새로 생성
    return client.projects.create(spec), True


def _field(value: Any, name: str) -> Any:
    """dictionary와 SDK resource 객체에서 같은 방식으로 필드를 읽는 함수."""
    # 테스트 dictionary와 실제 CVAT SDK 객체를 같은 방식으로 읽기 위한 호환 함수
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _enum_value(value: Any) -> Any:
    """SDK enum이면 원시 값을 꺼내고 일반 값이면 그대로 반환하는 함수."""
    # SDK enum과 일반 문자열을 비교 가능한 값으로 맞추는 함수
    return getattr(value, "value", value)


def _build_parser() -> argparse.ArgumentParser:
    """CVAT Project 생성 CLI가 지원하는 명령행 인자를 구성하는 함수."""
    # Project 이름과 taxonomy 위치를 필요할 때 덮어쓸 수 있게 구성한 CLI 인자
    parser = argparse.ArgumentParser(
        description="Create or reuse a taxonomy-backed CVAT polygon project."
    )
    parser.add_argument("--modality", required=True, help="Project modality, such as RT or VT")
    parser.add_argument("--name", help="CVAT project name (default: Welding QA <MODALITY>)")
    parser.add_argument(
        "--taxonomy",
        type=Path,
        help="Path to a custom taxonomy YAML (defaults to packaged canonical taxonomy)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """환경 설정부터 Project 생성 결과 출력까지 연결하는 CLI 진입점."""
    args = _build_parser().parse_args(argv)
    modality = args.modality.strip().upper()
    project_name = args.name or f"Welding QA {modality}"

    try:
        # 로컬 taxonomy와 인증 설정을 읽은 뒤 호환성 검사를 마친 SDK client를 준비
        taxonomy = (
            TaxonomyConfig.load_from_yaml(args.taxonomy)
            if args.taxonomy
            else TaxonomyConfig.load_default()
        )
        settings = CvatSettings.from_environ()
        client = connect_cvat(settings)
        # 성공·실패와 관계없이 SDK 세션을 닫아 연결 자원을 정리하는 코드
        try:
            project, created = ensure_cvat_project(
                client,
                project_name,
                taxonomy,
                modality,
            )
        finally:
            client.close()
    except (CvatIntegrationError, ParsingError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # 자동화 스크립트가 읽을 수 있도록 생성 여부와 URL을 한 줄 JSON으로 출력하는 코드
    print(
        json.dumps(
            {
                "id": _field(project, "id"),
                "name": _field(project, "name"),
                "modality": modality,
                "created": created,
                "url": f"{settings.url.rstrip('/')}/projects/{_field(project, 'id')}",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
