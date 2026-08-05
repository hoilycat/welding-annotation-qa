from dataclasses import dataclass
from pathlib import Path

import pytest

from welding_qa.cvat_project import (
    CvatIntegrationError,
    CvatSettings,
    build_cvat_project_spec,
    ensure_cvat_project,
)
from welding_qa.models import ParsingError
from welding_qa.taxonomy import TaxonomyConfig


@pytest.fixture
def taxonomy() -> TaxonomyConfig:
    yaml_path = Path(__file__).resolve().parents[1] / "configs" / "taxonomy.yaml"
    return TaxonomyConfig.load_from_yaml(yaml_path)


@dataclass
class FakeLabel:
    name: str
    type: str = "polygon"


@dataclass
class FakeProject:
    id: int
    name: str
    label_names: list[str]

    def get_labels(self) -> list[FakeLabel]:
        return [FakeLabel(name) for name in self.label_names]


class FakeProjectsRepo:
    def __init__(self, projects: list[FakeProject] | None = None):
        self.items = projects or []
        self.created_specs: list[dict[str, object]] = []

    def list(self) -> list[FakeProject]:
        return self.items

    def create(self, spec: dict[str, object]) -> FakeProject:
        self.created_specs.append(spec)
        labels = [label["name"] for label in spec["labels"]]  # type: ignore[index]
        project = FakeProject(42, str(spec["name"]), labels)
        self.items.append(project)
        return project


class FakeClient:
    def __init__(self, projects: list[FakeProject] | None = None):
        self.projects = FakeProjectsRepo(projects)


def test_settings_accept_username_and_password():
    settings = CvatSettings.from_environ(
        {
            "CVAT_URL": "http://localhost:8080",
            "CVAT_USERNAME": "admin",
            "CVAT_PASSWORD": "secret",
        }
    )
    assert settings.username == "admin"
    assert settings.password == "secret"
    assert settings.access_token is None


def test_settings_prefer_access_token():
    settings = CvatSettings.from_environ(
        {
            "CVAT_URL": "http://localhost:8080",
            "CVAT_ACCESS_TOKEN": "token",
        }
    )
    assert settings.access_token == "token"
    assert settings.username is None


def test_settings_require_credentials():
    with pytest.raises(CvatIntegrationError, match="CVAT_ACCESS_TOKEN"):
        CvatSettings.from_environ({"CVAT_URL": "http://localhost:8080"})


def test_build_project_spec_uses_canonical_polygon_labels(taxonomy: TaxonomyConfig):
    spec = build_cvat_project_spec("Welding QA RT", taxonomy, "rt")
    assert spec["name"] == "Welding QA RT"
    assert [label["name"] for label in spec["labels"]] == list(
        taxonomy.canonical_classes
    )
    assert {label["type"] for label in spec["labels"]} == {"polygon"}
    assert len({label["color"] for label in spec["labels"]}) == 6


@pytest.mark.parametrize("modality", ["", "INVALID"])
def test_build_project_spec_rejects_invalid_modality(
    taxonomy: TaxonomyConfig, modality: str
):
    with pytest.raises(ParsingError):
        build_cvat_project_spec("Welding QA", taxonomy, modality)


def test_ensure_project_creates_missing_project(taxonomy: TaxonomyConfig):
    client = FakeClient()
    project, created = ensure_cvat_project(client, "Welding QA RT", taxonomy, "RT")
    assert created is True
    assert project.id == 42
    assert len(client.projects.created_specs) == 1


def test_ensure_project_reuses_matching_project(taxonomy: TaxonomyConfig):
    existing = FakeProject(7, "Welding QA RT", list(taxonomy.canonical_classes))
    client = FakeClient([existing])
    project, created = ensure_cvat_project(client, "Welding QA RT", taxonomy, "RT")
    assert created is False
    assert project is existing
    assert client.projects.created_specs == []


def test_ensure_project_rejects_mismatched_existing_labels(taxonomy: TaxonomyConfig):
    client = FakeClient([FakeProject(7, "Welding QA RT", ["porosity"])])
    with pytest.raises(CvatIntegrationError, match="has different labels"):
        ensure_cvat_project(client, "Welding QA RT", taxonomy, "RT")


def test_ensure_project_rejects_non_polygon_existing_label(taxonomy: TaxonomyConfig):
    existing = FakeProject(7, "Welding QA RT", list(taxonomy.canonical_classes))
    existing.get_labels = lambda: [  # type: ignore[method-assign]
        FakeLabel(name, "rectangle" if name == "porosity" else "polygon")
        for name in taxonomy.canonical_classes
    ]
    client = FakeClient([existing])
    with pytest.raises(CvatIntegrationError, match="has different labels"):
        ensure_cvat_project(client, "Welding QA RT", taxonomy, "RT")
