from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import sys

import pytest

from welding_qa.cvat_project import CvatIntegrationError
from welding_qa.cvat_task import (
    build_cvat_task_spec,
    collect_image_paths,
    ensure_cvat_task,
)
from welding_qa.models import ParsingError


@dataclass
class FakeFrame:
    name: str


@dataclass
class FakeTask:
    id: int
    name: str
    frame_names: list[str]
    annotations: dict[str, list[object]] = field(
        default_factory=lambda: {"shapes": [], "tracks": [], "tags": []}
    )
    set_annotations_calls: int = 0

    def get_frames_info(self) -> list[FakeFrame]:
        return [FakeFrame(name) for name in self.frame_names]

    def get_annotations(self) -> dict[str, list[object]]:
        return self.annotations

    def set_annotations(self, payload: dict[str, list[object]]) -> None:
        self.set_annotations_calls += 1
        self.annotations = payload


class FakeProject:
    def __init__(self, tasks: list[FakeTask] | None = None):
        self.id = 7
        self._tasks = tasks or []

    def get_tasks(self) -> list[FakeTask]:
        return self._tasks


class FakeTasksRepo:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def create_from_data(self, **kwargs: object) -> FakeTask:
        self.calls.append(kwargs)
        spec = kwargs["spec"]
        resources = kwargs["resources"]
        assert isinstance(spec, dict)
        assert isinstance(resources, list)
        return FakeTask(42, str(spec["name"]), [Path(path).name for path in resources])


class FakeClient:
    def __init__(self):
        self.tasks = FakeTasksRepo()


def _make_images(tmp_path: Path, names: list[str]) -> list[Path]:
    paths = []
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
        paths.append(path)
    return paths


def test_collect_image_paths_recurses_and_sorts(tmp_path: Path):
    _make_images(tmp_path, ["b.png", "nested/a.JPG", "ignored.txt"])
    paths = collect_image_paths(tmp_path)
    assert [path.name for path in paths] == ["b.png", "a.JPG"]


def test_collect_image_paths_rejects_duplicate_names(tmp_path: Path):
    _make_images(tmp_path, ["one/image.png", "two/image.png"])
    with pytest.raises(ParsingError, match="filenames must be unique"):
        collect_image_paths(tmp_path)


def test_build_task_spec_validates_name_and_project_id():
    assert build_cvat_task_spec("RT batch", 7) == {"name": "RT batch", "project_id": 7}
    with pytest.raises(ParsingError, match="task name"):
        build_cvat_task_spec(" ", 7)
    with pytest.raises(ParsingError, match="project ID"):
        build_cvat_task_spec("RT batch", False)


def test_ensure_task_creates_and_uploads_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    images = _make_images(tmp_path, ["001.png", "002.png"])
    client = FakeClient()
    project = FakeProject()
    monkeypatch.setattr("welding_qa.cvat_task._get_local_resource_type", lambda: "local")

    task, created = ensure_cvat_task(client, project, "RT batch", images)

    assert created is True
    assert task.id == 42
    assert client.tasks.calls[0]["spec"] == {"name": "RT batch", "project_id": 7}
    assert client.tasks.calls[0]["resource_type"] == "local"


def test_ensure_task_rejects_non_path_image_value(tmp_path: Path):
    image = _make_images(tmp_path, ["001.png"])[0]

    with pytest.raises(ParsingError, match="index 1 must be a string or Path"):
        ensure_cvat_task(FakeClient(), FakeProject(), "RT batch", [image, None])


def test_ensure_task_reuses_matching_frames(tmp_path: Path):
    images = _make_images(tmp_path, ["001.png", "002.png"])
    existing = FakeTask(9, "RT batch", ["001.png", "002.png"])
    client = FakeClient()

    task, created = ensure_cvat_task(client, FakeProject([existing]), "RT batch", images)

    assert created is False
    assert task is existing
    assert client.tasks.calls == []


def test_ensure_task_rejects_mismatched_frames(tmp_path: Path):
    images = _make_images(tmp_path, ["001.png", "002.png"])
    existing = FakeTask(9, "RT batch", ["other.png"])
    with pytest.raises(CvatIntegrationError, match="has different frames"):
        ensure_cvat_task(FakeClient(), FakeProject([existing]), "RT batch", images)


def test_ensure_task_rejects_duplicate_names(tmp_path: Path):
    images = _make_images(tmp_path, ["001.png"])
    tasks = [FakeTask(1, "RT batch", ["001.png"]), FakeTask(2, "RT batch", ["001.png"])]
    with pytest.raises(CvatIntegrationError, match="Multiple CVAT tasks"):
        ensure_cvat_task(FakeClient(), FakeProject(tasks), "RT batch", images)


def test_build_label_id_mappings():
    from welding_qa.cvat_task import build_label_id_mappings
    project = FakeProject()
    project.labels = [{"id": 10, "name": "porosity"}, {"id": 11, "name": "crack"}]
    c2i, i2n = build_label_id_mappings(project)
    assert c2i == {"porosity": 10, "crack": 11}
    assert i2n == {10: "porosity", 11: "crack"}


def test_load_annotations_for_images(tmp_path: Path):
    from welding_qa.cvat_task import load_annotations_for_images
    from welding_qa.taxonomy import TaxonomyConfig

    taxonomy = TaxonomyConfig({
        "canonical_classes": {
            "porosity": {
                "korean_name": "기포",
                "aliases": [],
                "allowed_modalities": ["RT"],
            }
        }
    })

    img_dir = tmp_path / "images"
    ann_dir = tmp_path / "annotations"
    img_paths = _make_images(img_dir, ["001.png", "002.png"])

    json_file = ann_dir / "001.json"
    json_file.parent.mkdir(parents=True, exist_ok=True)
    json_file.write_text(
        '{"modality":"RT","annotations":[{"label":"porosity","polygon":{"x":[10,20,10],"y":[10,10,20]}}]}',
        encoding="utf-8",
    )

    result = load_annotations_for_images(ann_dir, img_paths, taxonomy, modality="RT")
    assert "001.png" in result
    assert len(result["001.png"]) == 1
    assert result["001.png"][0].label_canonical == "porosity"
    assert result["002.png"] == []


def test_load_annotations_rejects_ambiguous_image_stems(tmp_path: Path):
    from welding_qa.cvat_task import load_annotations_for_images
    from welding_qa.taxonomy import TaxonomyConfig

    taxonomy = TaxonomyConfig({"canonical_classes": {}})
    images = _make_images(tmp_path / "images", ["sample.jpg", "sample.png"])
    annotation_dir = tmp_path / "annotations"
    annotation_dir.mkdir()

    with pytest.raises(ParsingError, match="Image filenames must have unique stems"):
        load_annotations_for_images(annotation_dir, images, taxonomy)


def test_load_annotations_rejects_duplicate_json_stems(tmp_path: Path):
    from welding_qa.cvat_task import load_annotations_for_images
    from welding_qa.taxonomy import TaxonomyConfig

    taxonomy = TaxonomyConfig({"canonical_classes": {}})
    images = _make_images(tmp_path / "images", ["sample.png"])
    annotation_dir = tmp_path / "annotations"
    for relative_path in ("one/sample.json", "two/sample.JSON"):
        path = annotation_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"annotations": []}', encoding="utf-8")

    with pytest.raises(ParsingError, match="Annotation JSON filenames must have unique stems"):
        load_annotations_for_images(annotation_dir, images, taxonomy)


def test_sync_and_export_task_annotations(tmp_path: Path):
    from welding_qa.cvat_task import export_task_annotations, sync_task_annotations
    from welding_qa.models import DefectAnnotation, Polygon
    from welding_qa.taxonomy import TaxonomyConfig

    taxonomy = TaxonomyConfig({
        "canonical_classes": {
            "porosity": {
                "korean_name": "기포",
                "aliases": [],
                "allowed_modalities": ["RT"],
            }
        }
    })

    project = FakeProject()
    project.labels = [{"id": 101, "name": "porosity"}]

    task = FakeTask(1, "RT batch", ["001.png"])
    ann = DefectAnnotation(
        label_original="porosity",
        label_canonical="porosity",
        polygon=Polygon(x=(10, 20, 10), y=(10, 10, 20)),
        modality="RT",
    )

    ann_map = {"001.png": [ann]}
    synced_count = sync_task_annotations(task, project, ann_map)
    assert synced_count == 1
    assert task.set_annotations_calls == 1
    assert len(task.annotations["shapes"]) == 1
    assert task.annotations["shapes"][0]["label_id"] == 101

    exported = export_task_annotations(task, project, taxonomy, modality="RT")
    assert "001.png" in exported
    assert len(exported["001.png"]) == 1
    assert exported["001.png"][0].label_canonical == "porosity"


def test_sync_rejects_existing_annotations_without_explicit_replace():
    from welding_qa.cvat_task import sync_task_annotations

    project = FakeProject()
    project.labels = []
    task = FakeTask(1, "RT batch", ["001.png"])
    task.annotations["shapes"] = [{"id": 99}]

    with pytest.raises(CvatIntegrationError, match="already has annotations"):
        sync_task_annotations(task, project, {"001.png": []})

    synced_count = sync_task_annotations(
        task,
        project,
        {"001.png": []},
        replace_existing=True,
    )
    assert synced_count == 0
    assert task.annotations == {"shapes": [], "tracks": [], "tags": []}
    assert task.set_annotations_calls == 1


def test_export_rejects_frame_stem_collision():
    from welding_qa.cvat_task import export_task_annotations
    from welding_qa.taxonomy import TaxonomyConfig

    task = FakeTask(1, "RT batch", ["sample.jpg", "sample.png"])
    project = FakeProject()
    project.labels = []
    taxonomy = TaxonomyConfig({"canonical_classes": {}})

    with pytest.raises(ParsingError, match="CVAT frame filenames must have unique stems"):
        export_task_annotations(task, project, taxonomy)


def test_module_help_does_not_emit_runtime_warning():
    result = subprocess.run(
        [sys.executable, "-m", "welding_qa.cvat_task", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "RuntimeWarning" not in result.stderr
