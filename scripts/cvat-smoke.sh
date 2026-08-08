#!/usr/bin/env bash
# CVAT API에 이미지와 annotation을 왕복시켜 배포 전 통합 동작을 확인하는 smoke test
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON:-python}"
modality="RT"
images=""
annotations=""
export_dir=""
project_name=""
task_name=""
replace=0

usage() {
    cat <<'EOF'
Usage: scripts/cvat-smoke.sh --images DIR --export-dir DIR [options]

Options:
  --images DIR          Image directory to upload (required)
  --annotations DIR     RIAWELC JSON directory to synchronize
  --export-dir DIR      Directory for canonical JSON export (required)
  --modality MODALITY   RT or VT (default: RT)
  --project-name NAME   Existing/new CVAT Project name
  --task-name NAME      Existing/new CVAT Task name
  --replace             Explicitly replace existing Task annotations
  --help                Show this help

Set PYTHON to select the Python executable and load CVAT credentials from .env.cvat.
EOF
}

while (($# > 0)); do
    case "$1" in
        --images) images="${2:?--images requires a directory}"; shift 2 ;;
        --annotations) annotations="${2:?--annotations requires a directory}"; shift 2 ;;
        --export-dir) export_dir="${2:?--export-dir requires a directory}"; shift 2 ;;
        --modality) modality="${2:?--modality requires RT or VT}"; shift 2 ;;
        --project-name) project_name="${2:?--project-name requires a value}"; shift 2 ;;
        --task-name) task_name="${2:?--task-name requires a value}"; shift 2 ;;
        --replace) replace=1; shift ;;
        --help) usage; exit 0 ;;
        *) echo "error: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ -z "$images" || -z "$export_dir" ]]; then
    echo "error: --images and --export-dir are required" >&2
    usage >&2
    exit 2
fi

if [[ -f "$repo_root/.env.cvat" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$repo_root/.env.cvat"
    set +a
fi

common_args=(--modality "$modality" --images "$images")
[[ -n "$project_name" ]] && common_args+=(--project-name "$project_name")
[[ -n "$task_name" ]] && common_args+=(--task-name "$task_name")

echo "[1/3] Ensure CVAT Task and upload images"
(cd "$repo_root" && "$python_bin" -m welding_qa.cvat_task "${common_args[@]}")

if [[ -n "$annotations" ]]; then
    echo "[2/3] Synchronize annotations"
    sync_args=("${common_args[@]}" --annotations "$annotations")
    ((replace)) && sync_args+=(--replace-annotations)
    (cd "$repo_root" && "$python_bin" -m welding_qa.cvat_task "${sync_args[@]}")
else
    echo "[2/3] No annotation directory supplied; skipping synchronization"
fi

echo "[3/3] Export and validate canonical JSON"
export_args=("${common_args[@]}" --export-annotations "$export_dir")
(cd "$repo_root" && "$python_bin" -m welding_qa.cvat_task "${export_args[@]}")

EXPORT_DIR="$export_dir" IMAGES_DIR="$images" "$python_bin" - <<'PY'
import json
import os
from pathlib import Path

export_dir = Path(os.environ["EXPORT_DIR"])
images_dir = Path(os.environ["IMAGES_DIR"])
expected = sorted(
    path.name
    for path in images_dir.rglob("*")
    if path.is_file() and path.suffix.lower() in {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
)
actual = sorted(path.stem + ".json" for path in export_dir.glob("*.json"))
expected_json = sorted(Path(name).stem + ".json" for name in expected)
if actual != expected_json:
    raise SystemExit(f"exported files do not match images: expected {expected_json}, got {actual}")
for path in sorted(export_dir.glob("*.json")):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("annotations"), list):
        raise SystemExit(f"export file has invalid annotations list: {path}")
print(f"Smoke test passed: {len(actual)} exported files match {len(expected)} images.")
PY
