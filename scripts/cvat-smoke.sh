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

absolute_existing_dir() {
    local directory="$1"
    if [[ ! -d "$directory" ]]; then
        echo "error: directory does not exist: $directory" >&2
        exit 1
    fi
    (cd "$directory" && pwd -P)
}

# 호출 위치와 무관하게 CVAT CLI와 최종 검증기가 같은 directory를 사용하게 한다.
images="$(absolute_existing_dir "$images")"
if [[ -n "$annotations" ]]; then
    annotations="$(absolute_existing_dir "$annotations")"
fi
mkdir -p "$export_dir"
export_dir="$(absolute_existing_dir "$export_dir")"

common_args=(--modality "$modality" --images "$images")
[[ -n "$project_name" ]] && common_args+=(--project-name "$project_name")
[[ -n "$task_name" ]] && common_args+=(--task-name "$task_name")

if [[ -n "$annotations" ]]; then
    echo "[1/2] Validate input, upload images, and synchronize annotations"
    sync_args=("${common_args[@]}" --annotations "$annotations")
    ((replace)) && sync_args+=(--replace-annotations)
    (cd "$repo_root" && "$python_bin" -m welding_qa.cvat_task "${sync_args[@]}")
else
    echo "[1/2] Ensure CVAT Task and upload images"
    (cd "$repo_root" && "$python_bin" -m welding_qa.cvat_task "${common_args[@]}")
fi

echo "[2/2] Export and validate canonical JSON"
export_args=("${common_args[@]}" --export-annotations "$export_dir")
(cd "$repo_root" && "$python_bin" -m welding_qa.cvat_task "${export_args[@]}")

validation_args=(
    --images "$images"
    --export-dir "$export_dir"
    --modality "$modality"
)
[[ -n "$annotations" ]] && validation_args+=(--annotations "$annotations")
(cd "$repo_root" && "$python_bin" -m welding_qa.smoke_validation "${validation_args[@]}")
