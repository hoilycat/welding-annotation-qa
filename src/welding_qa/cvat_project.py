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


_LABEL_COLORS = (
    "#E76F51",
    "#F4A261",
    "#E9C46A",
    "#2A9D8F",
    "#457B9D",
    "#6D597A",
)


class CvatIntegrationError(RuntimeError):
    """Raised when the CVAT SDK cannot connect or authenticate."""


@dataclass(frozen=True)
class CvatSettings:
    url: str
    username: str | None = None
    password: str | None = None
    access_token: str | None = None

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> CvatSettings:
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
    """Create an authenticated, version-checked CVAT SDK client."""
    try:
        from cvat_sdk import make_client
    except ImportError as exc:
        raise CvatIntegrationError(
            'CVAT SDK is not installed. Run: pip install -e ".[dev,cvat]"'
        ) from exc

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
    """Build a CVAT project payload from modality-compatible canonical labels."""
    project_name = name.strip() if isinstance(name, str) else ""
    if not project_name:
        raise ParsingError("CVAT project name must be a non-empty string.")
    if not isinstance(modality, str) or not modality.strip():
        raise ParsingError("CVAT project modality must be a non-empty string.")

    normalized_modality = modality.strip().upper()
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
    """Create a taxonomy project, or reuse an exact-name project with matching labels."""
    spec = build_cvat_project_spec(name, taxonomy, modality)
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

    return client.projects.create(spec), True


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or reuse a taxonomy-backed CVAT polygon project."
    )
    parser.add_argument("--modality", required=True, help="Project modality, such as RT or VT")
    parser.add_argument("--name", help="CVAT project name (default: Welding QA <MODALITY>)")
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=Path("configs/taxonomy.yaml"),
        help="Path to the canonical taxonomy YAML",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    modality = args.modality.strip().upper()
    project_name = args.name or f"Welding QA {modality}"

    try:
        taxonomy = TaxonomyConfig.load_from_yaml(args.taxonomy)
        settings = CvatSettings.from_environ()
        client = connect_cvat(settings)
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
