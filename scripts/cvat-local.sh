#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="${CVAT_RUNTIME_DIR:-$repo_root/.local/cvat}"
env_file="$repo_root/.env.cvat"

if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
fi

cvat_version="${CVAT_VERSION:-v2.70.0}"
cvat_host="${CVAT_HOST:-localhost}"
cvat_port="${CVAT_PORT:-8080}"

usage() {
    cat <<'EOF'
Usage: scripts/cvat-local.sh <command>

Commands:
  bootstrap   Clone the pinned CVAT release into .local/cvat
  pull        Pull the pinned CVAT container images
  up          Start the local CVAT stack
  down        Stop the stack without deleting its data volumes
  status      Show container status
  health      Run CVAT's server health check
  logs        Follow CVAT server logs
  superuser   Create a CVAT administrator interactively
  url         Print the local CVAT URL
EOF
}

require_docker() {
    if ! docker info >/dev/null 2>&1; then
        echo "Docker is not running. Start Docker Desktop and retry." >&2
        exit 1
    fi
}

ensure_source() {
    if [[ ! -d "$runtime_dir/.git" ]]; then
        mkdir -p "$(dirname "$runtime_dir")"
        git clone --depth 1 --branch "$cvat_version" \
            https://github.com/cvat-ai/cvat.git "$runtime_dir"
    fi

    local installed_version
    installed_version="$(git -C "$runtime_dir" describe --tags --exact-match 2>/dev/null || true)"
    if [[ "$installed_version" != "$cvat_version" ]]; then
        echo "Expected CVAT $cvat_version, found ${installed_version:-an untagged checkout}." >&2
        echo "Set CVAT_RUNTIME_DIR to another directory or update the existing checkout." >&2
        exit 1
    fi
}

compose() {
    (
        cd "$runtime_dir"
        CVAT_VERSION="$cvat_version" \
        CVAT_HOST="$cvat_host" \
        CVAT_PORT="$cvat_port" \
            docker compose "$@"
    )
}

command="${1:-}"
case "$command" in
    bootstrap)
        ensure_source
        echo "CVAT $cvat_version is ready in $runtime_dir"
        ;;
    pull)
        require_docker
        ensure_source
        compose pull
        ;;
    up)
        require_docker
        ensure_source
        compose up -d
        echo "CVAT is starting at http://$cvat_host:$cvat_port"
        ;;
    down)
        require_docker
        ensure_source
        compose down
        ;;
    status)
        require_docker
        ensure_source
        compose ps
        ;;
    health)
        require_docker
        docker exec -t cvat_server python manage.py health_check
        ;;
    logs)
        require_docker
        ensure_source
        compose logs --follow cvat_server
        ;;
    superuser)
        require_docker
        docker exec -it cvat_server bash -ic 'python3 ~/manage.py createsuperuser'
        ;;
    url)
        echo "http://$cvat_host:$cvat_port"
        ;;
    *)
        usage
        exit 1
        ;;
esac
