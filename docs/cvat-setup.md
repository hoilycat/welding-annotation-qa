# CVAT 로컬 서버 설정

이 문서는 Docker로 CVAT 서버를 실행하고 계정과 연결 상태를 확인하는 절차를 설명합니다. 명령은 저장소 루트에서 실행합니다.

## 준비물

- Python 3.10 이상
- Git
- Docker Desktop

Docker Desktop을 먼저 실행한 뒤 아래 명령으로 상태를 확인합니다.

```bash
docker version
docker compose version
```

## 환경 파일

CVAT 접속 정보는 Git에 커밋하지 않는 `.env.cvat`에 저장합니다.

```bash
# macOS / Linux
cp .env.cvat.example .env.cvat

# Windows PowerShell
Copy-Item .env.cvat.example .env.cvat
```

`.env.cvat` 예시:

```dotenv
CVAT_URL=http://localhost:8080
CVAT_USERNAME=<your-local-username>
CVAT_PASSWORD=<your-local-password>
CVAT_ACCESS_TOKEN=<optional-access-token>
```

비밀번호나 토큰을 README, 커밋, 터미널 캡처에 포함하지 마세요.

## 서버 시작

### macOS / Linux

```bash
chmod +x scripts/cvat-local.sh scripts/cvat-smoke.sh
./scripts/cvat-local.sh bootstrap
./scripts/cvat-local.sh up
```

### Windows PowerShell

```powershell
.\scripts\cvat-local.ps1 bootstrap
.\scripts\cvat-local.ps1 up
```

서버가 준비되면 브라우저에서 <http://localhost:8080>을 엽니다. 최초 실행은 Docker 이미지 다운로드와 데이터베이스 초기화 때문에 시간이 걸릴 수 있습니다.

## 계정 생성

`.env.cvat`에 적은 계정으로 로그인되지 않으면 superuser를 생성하거나 갱신합니다.

```bash
# macOS / Linux
./scripts/cvat-local.sh superuser

# Windows PowerShell
.\scripts\cvat-local.ps1 superuser
```

로그인 칸에는 `CVAT_USERNAME` 또는 CVAT가 허용하는 이메일을 사용합니다. 로컬 전용 이메일이 필요하면 `username@localhost.invalid`처럼 실제 수신되지 않는 주소를 사용할 수 있습니다.

## 서버 관리 명령

| 작업 | macOS / Linux | Windows PowerShell |
|---|---|---|
| 초기 설정 | `./scripts/cvat-local.sh bootstrap` | `.\scripts\cvat-local.ps1 bootstrap` |
| 시작 | `./scripts/cvat-local.sh up` | `.\scripts\cvat-local.ps1 up` |
| 상태 확인 | `./scripts/cvat-local.sh status` | `.\scripts\cvat-local.ps1 status` |
| 로그 확인 | `./scripts/cvat-local.sh logs` | `.\scripts\cvat-local.ps1 logs` |
| 계정 생성 | `./scripts/cvat-local.sh superuser` | `.\scripts\cvat-local.ps1 superuser` |
| 종료 | `./scripts/cvat-local.sh down` | `.\scripts\cvat-local.ps1 down` |

`down`은 컨테이너를 중지하지만 CVAT 볼륨은 유지합니다. 볼륨 삭제는 프로젝트와 어노테이션을 잃을 수 있으므로 백업 없이 실행하지 마세요.

## 연결 확인

서버 연결을 먼저 확인합니다.

```bash
# macOS / Linux
./scripts/cvat-local.sh health

# Windows PowerShell
.\scripts\cvat-local.ps1 health
```

테스트 이미지의 업로드·동기화·내보내기를 포함한 smoke test:

```bash
# macOS / Linux
./scripts/cvat-smoke.sh \
  --images data/images \
  --annotations data/annotations \
  --export-dir reports/cvat-smoke

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File .\scripts\cvat-smoke.ps1 `
  -Images data\images `
  -Annotations data\annotations `
  -ExportDir reports\cvat-smoke
```

smoke test는 다음 항목을 확인합니다.

1. CVAT Project와 Task 생성 또는 재사용
2. 테스트 이미지와 선택적 어노테이션 업로드
3. canonical JSON 내보내기

## 문제 해결

- 서버가 열리지 않으면 Docker Desktop 실행 여부와 `status`, `logs` 결과를 확인합니다.
- `Unable to login with provided credentials`가 나오면 아이디·이메일·비밀번호가 `.env.cvat`과 같은지 확인한 뒤 `superuser`를 실행합니다.
- 8080 포트를 이미 사용 중이면 `.env.cvat`과 CVAT 설정의 포트를 함께 변경해야 합니다.
- CVAT native backup은 복원용 원본입니다. canonical JSON이나 COCO/YOLO 출력만으로는 CVAT Project 전체를 그대로 복원할 수 없습니다.
