#!/usr/bin/env bash
# 명령 실패, 미정의 변수, pipeline 중간 실패를 즉시 중단하는 안전 설정
set -euo pipefail

# 실행 위치와 관계없이 저장소 루트와 로컬 CVAT 경로를 계산하는 코드
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="${CVAT_RUNTIME_DIR:-$repo_root/.local/cvat}"
env_file="$repo_root/.env.cvat"

# 로컬 전용 설정과 인증 정보를 현재 script 환경변수로 불러오는 코드
if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
fi

cvat_version="${CVAT_VERSION:-v2.71.0}"
cvat_host="${CVAT_HOST:-localhost}"
cvat_port="${CVAT_PORT:-8080}"
cvat_url="${CVAT_URL:-http://$cvat_host:$cvat_port}"

# 지원하는 하위 명령과 용도를 출력하는 도움말
usage() {
    cat <<'EOF'
Usage (macOS/Linux): scripts/cvat-local.sh <command>

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

# Docker Desktop daemon이 실제로 응답하는지 확인하는 사전 검사
require_docker() {
    if ! docker info >/dev/null 2>&1; then
        echo "Docker is not running. Start Docker Desktop and retry." >&2
        exit 1
    fi
}

# 고정한 CVAT tag를 shallow clone하고 기존 checkout의 버전도 확인하는 코드
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

# CVAT checkout에서 host, port, version을 전달해 docker compose를 실행하는 함수
compose() {
    (
        cd "$runtime_dir"
        CVAT_VERSION="$cvat_version" \
        CVAT_HOST="$cvat_host" \
        CVAT_PORT="$cvat_port" \
            docker compose "$@"
    )
}

# 사용자 명령을 공통 준비 단계와 실제 Docker 작업으로 연결하는 분기
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
        # API가 응답하면 Docker socket 권한이나 compose checkout 없이도 실제 서비스 상태를 확인
        if curl --fail --silent --show-error --max-time 5 \
            "$cvat_url/api/server/about" >/dev/null; then
            echo "CVAT API is healthy: $cvat_url"
        else
            # API가 아직 뜨지 않은 경우에만 Docker 내부 health check로 원인을 확인
            require_docker
            docker exec -t cvat_server python manage.py health_check
        fi
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
