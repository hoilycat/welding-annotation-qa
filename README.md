<div align="center">

# 🔥 welding-annotation-qa

### 용접 결함 라벨을 가지런히 정리하는 데이터 QA 도구

![version](https://img.shields.io/badge/version-0.3-E76F51?style=flat-square)
![status](https://img.shields.io/badge/status-foundation-F4A261?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Pytest](https://img.shields.io/badge/tests-pytest-2A9D8F?style=flat-square&logo=pytest&logoColor=white)

> **“모델이 배우기 전에, 라벨부터 가지런히.”**<br>
> 제각각인 용접 결함 Polygon JSON을 검사하고 하나의 표준 이름으로 정리합니다.

</div>

---

## 🧹 어떤 프로젝트인가요?

같은 용접 결함인데도 데이터마다 이름이 다를 수 있습니다.

```text
기공 · POROSITY · gas_pore · blowhole
                    ↓
               ✨ porosity ✨
```

`welding-annotation-qa`는 이렇게 제각각인 라벨을 하나의 **canonical taxonomy**로 통일하고, Polygon 좌표와 JSON 구조에 문제가 없는지 모델 학습 전에 확인합니다.

쉽게 말하면, **용접 데이터가 모델에게 들어가기 전에 한 번 정리해 주는 라벨 정리반**입니다. 🧤

> 📍 현재 버전은 **v0.3**입니다.<br>
> JSON 검증, 라벨 정규화, CVAT Project/Task 생성과 annotation 동기화를 지원합니다.<br>
> Canonical polygon export와 dataset QA 리포트를 제공하며 YOLO/COCO export는 다음 단계입니다.

현재 테스트 스위트는 **125개**이며, 로컬 CVAT에서 이미지 업로드 → annotation 동기화 →
canonical JSON export 전체 smoke test도 통과했습니다.

---

## ✨ v0.3에서 할 수 있는 일

| 기능 | 하는 일 |
|---|---|
| 🏷️ 라벨 정규화 | `기공`, `POROSITY`, `gas_pore`를 `porosity`로 통일 |
| 📐 Polygon 검사 | 좌표 구조, 면적, 자기교차, 중복점과 이미지 경계 확인 |
| 🚨 오류 감지 | 올바르지 않은 annotation 항목을 즉시 알림 |
| 🩻 검사 방식 확인 | 결함별 RT/VT modality 허용 여부 검증 |
| 🖼️ 메타데이터 보존 | `image_id`, `filename`, `width`, `height` 유지 |
| 🌱 정상 이미지 허용 | 결함이 없는 `annotations: []`도 정상 처리 |
| 📤 CVAT 등록 | taxonomy Project와 이미지 Task를 생성하거나 안전하게 재사용 |

입력은 다음 세 가지 형태를 지원합니다.

- JSON 파일 경로
- JSON 문자열
- Python dictionary

JSON의 annotation 목록 이름은 `annotations`, `shapes`, `objects` 중 하나를 사용할 수 있습니다.
`width`와 `height`가 있으면 Polygon 좌표는 `0 ≤ x ≤ width`,
`0 ≤ y ≤ height` 범위여야 하며 연속점과 닫힘점은 중복될 수 없습니다.

---

## 🏷️ Canonical Defect Friends

현재 함께 정리하는 용접 결함 친구들은 총 6종입니다.

| 아이콘 | Canonical label | 한글 이름 |
|:---:|---|---|
| 🫧 | `porosity` | 기공 |
| 🪨 | `slag_inclusion` | 슬래그 혼입 |
| ⚡ | `crack` | 균열 |
| 🧩 | `lack_of_fusion` | 융합 불량 |
| 🕳️ | `incomplete_penetration` | 용입 부족 |
| 🌙 | `undercut` | 언더컷 |

라벨과 alias 설정은 [`configs/taxonomy.yaml`](configs/taxonomy.yaml)에서 관리합니다.

---

## 🚀 빠르게 시작하기

Python 3.10 이상이 필요합니다.

```bash
pip install -e ".[dev]"
pytest
```

Python 코드에서는 이렇게 사용할 수 있습니다.

```python
from welding_qa import TaxonomyConfig, parse_riawelc_json

taxonomy = TaxonomyConfig.load_from_yaml("configs/taxonomy.yaml")
annotations = parse_riawelc_json(
    "tests/fixtures/sample_annotation.json",
    taxonomy,
)

print(annotations[0].label_original)   # 기공
print(annotations[0].label_canonical)  # porosity
```

결함이 없는 깨끗한 이미지라면 아래처럼 작성할 수 있습니다.

```json
{
  "modality": "RT",
  "annotations": []
}
```

이 경우 오류가 아니라 빈 annotation 목록을 반환합니다. 🌿

### CVAT Polygon payload 만들기

CVAT 프로젝트에서 조회한 label ID를 canonical label에 연결하면 검증된
annotation을 `LabeledShapeRequest` 형태로 변환할 수 있습니다.

```python
from welding_qa import annotations_to_cvat_shapes

label_ids = {"porosity": 7}  # CVAT 프로젝트의 실제 label ID
shapes = annotations_to_cvat_shapes(
    annotations,
    label_ids,
    frame=0,
)

cvat_payload = {
    "version": 0,
    "tags": [],
    "shapes": shapes,
    "tracks": [],
    "intervals": [],
}
```

각 Polygon 좌표는 CVAT 형식인 `[x1, y1, x2, y2, ...]`로 변환됩니다.
`cvat_shapes_to_annotations`를 사용하면 CVAT shape를 다시
`DefectAnnotation`으로 가져올 수 있습니다.

### 로컬 CVAT 환경 실행하기

Docker Desktop을 실행한 뒤 프로젝트에 고정된 CVAT 버전을 준비하고 시작할 수 있습니다.

macOS/Linux:

```bash
cp .env.cvat.example .env.cvat
./scripts/cvat-local.sh bootstrap
./scripts/cvat-local.sh up
```

Windows PowerShell:

```powershell
Copy-Item .env.cvat.example .env.cvat
powershell -ExecutionPolicy Bypass -File .\scripts\cvat-local.ps1 bootstrap
powershell -ExecutionPolicy Bypass -File .\scripts\cvat-local.ps1 up
```

CVAT는 기본적으로 <http://localhost:8080>에서 열립니다. 최초 관리자 계정은
서버가 준비된 다음 대화형 명령으로 생성합니다.

```bash
./scripts/cvat-local.sh health
./scripts/cvat-local.sh superuser
```

`health`는 Docker 내부 명령보다 먼저 CVAT API(`/api/server/about`)를 확인하므로,
Docker socket 권한이 제한된 환경에서도 실제 서비스가 응답하는지 판별할 수 있습니다.

이미지 업로드부터 annotation 동기화와 canonical export까지 한 번에 확인하려면
smoke test 스크립트를 사용할 수 있습니다. `--replace`는 기존 Task의 annotation을
명시적으로 교체하므로 테스트 전용 Task에서만 사용합니다.

```bash
PYTHON=.venv/bin/python ./scripts/cvat-smoke.sh \
  --images data/cvat-smoke-20260807 \
  --annotations data/rt-annotations \
  --export-dir reports/cvat-smoke \
  --replace
```

JSON 폴더만 검사하는 dataset QA 리포트는 다음처럼 생성합니다.

```bash
python -m welding_qa.qa_report \
  --annotations data/rt-annotations \
  --modality RT \
  --output reports/rt-qa.json
```

Windows에서는 같은 명령을 PowerShell 스크립트로 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\cvat-local.ps1 health
powershell -ExecutionPolicy Bypass -File .\scripts\cvat-local.ps1 superuser
```

Python SDK가 필요한 개발 환경은 서버와 같은 2.71 버전으로 설치됩니다.

```bash
pip install -e ".[dev,cvat]"
```

상태 확인과 종료에는 다음 명령을 사용합니다. `down`은 Docker 데이터 볼륨을
삭제하지 않으므로 생성한 사용자와 annotation이 유지됩니다.

```bash
./scripts/cvat-local.sh status
./scripts/cvat-local.sh down
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\cvat-local.ps1 status
powershell -ExecutionPolicy Bypass -File .\scripts\cvat-local.ps1 down
```

### 학교와 집에서 작업 이어가기

이미지 원본과 `.env.cvat`는 Git에 넣지 않고 별도로 보관합니다. 다른 컴퓨터에서 작업할 때는
같은 상대 경로로 이미지·RIAWELC JSON 폴더를 복원한 뒤 `.env.cvat`를 다시 설정합니다.

- CVAT annotation을 계속 편집하려면 CVAT의 **native dataset export**로 전체 백업합니다.
- 학습용 canonical polygon만 옮길 때는 `--export-annotations` 결과를 사용합니다.
- canonical export는 tracks, tags, attributes와 같은 CVAT 전체 메타데이터 백업을 대신하지 않습니다.
- `.env.cvat`에는 인증정보가 들어갈 수 있으므로 저장소에 커밋하지 않습니다.

`.env.cvat`에 관리자 계정 또는 Personal Access Token을 설정하면 canonical taxonomy로
RT/VT Polygon Project를 생성할 수 있습니다. 같은 이름과 label 구성을 가진
Project가 이미 있으면 새로 만들지 않고 재사용합니다.

```bash
set -a
source .env.cvat
set +a

python -m welding_qa.cvat_project --modality RT
python -m welding_qa.cvat_project --modality VT
```

이미지 폴더를 Project 아래 Task로 업로드할 때는 다음 명령을 사용합니다. 같은 이름의
Task가 있고 frame 파일명도 모두 같으면 기존 Task를 재사용합니다.

```bash
python -m welding_qa.cvat_task --modality RT --images data/rt-images
python -m welding_qa.cvat_task --modality VT --images data/vt-images
```

이미지와 같은 stem의 RIAWELC JSON을 함께 등록하거나 CVAT의 현재 polygon을 JSON으로
내보낼 수 있습니다. 예를 들어 `001.png`는 `001.json`과 매칭됩니다. 이미지 또는 JSON의
stem이 중복되거나, 이미지와 JSON이 서로 대응하지 않거나, JSON의 modality가 Task와
다르면 잘못된 매칭을 막기 위해 명령이 실패합니다. 결함이 없는 이미지도
`annotations: []`를 가진 JSON을 명시적으로 준비합니다.

```bash
python -m welding_qa.cvat_task --modality RT --images data/rt-images \
  --annotations data/rt-annotations

python -m welding_qa.cvat_task --modality RT --images data/rt-images \
  --export-annotations exports/rt-annotations
```

부분 annotation 세트를 의도적으로 올리는 경우에만 JSON이 없는 이미지를 빈 annotation으로
처리하는 옵션을 사용합니다. 이미지와 매칭되지 않는 JSON은 이 옵션으로도 허용하지 않습니다.

```bash
python -m welding_qa.cvat_task --modality RT --images data/rt-images \
  --annotations data/rt-annotations --allow-missing-annotations
```

기존 Task에 어노테이션이 있으면 작업자의 수정 내용을 보호하기 위해 업로드를 거부합니다.
`--export-annotations`는 모델 학습용 canonical polygon 내보내기이며 CVAT 전체 백업이
아닙니다. tracks, tags, attributes까지 보존하려면 CVAT의 native dataset export로 먼저
백업한 다음 명시적으로 교체 옵션을 사용합니다. tracks나 tags가 있는 Task의 canonical
export는 데이터 누락을 막기 위해 실패합니다.

```bash
python -m welding_qa.cvat_task --modality RT --images data/rt-images \
  --annotations data/rt-annotations --replace-annotations
```

Windows PowerShell에서는 `.env.cvat`을 현재 세션에 불러온 뒤 실행합니다.

```powershell
Get-Content .env.cvat | Where-Object { $_ -match '^[A-Za-z_][A-Za-z0-9_]*=' } | ForEach-Object {
    $name, $value = $_ -split '=', 2
    Set-Item -Path "Env:$name" -Value $value
}

python -m welding_qa.cvat_project --modality RT
python -m welding_qa.cvat_project --modality VT
python -m welding_qa.cvat_task --modality RT --images data/rt-images
python -m welding_qa.cvat_task --modality VT --images data/vt-images
```

---

## 🔄 데이터는 이렇게 흘러가요

```text
📁 원본 이미지 + 제각각인 Polygon JSON
                    ↓
          🧹 welding-annotation-qa
          ├─ JSON 구조 확인
          ├─ Polygon 기본 검사
          ├─ 라벨 이름 통일
          └─ RT/VT modality 확인
                    ↓
       ✨ 검증된 DefectAnnotation 목록
                    ↓
       🧩 CVAT Polygon shape 변환
                    ↓
          🔥 모델 학습과 결함 검출
```

---

## 🤝 WeldVision과는 어떤 사이인가요?

두 저장소는 용접 결함 데이터를 사이에 둔 **정리 담당과 활용 담당**입니다.

| 저장소 | 역할 |
|---|---|
| 🧹 `welding-annotation-qa` | 학습 전에 데이터를 검사하고 라벨을 통일 |
| 🔥 `WeldVision` | 정리된 데이터로 모델을 학습하고 결함을 검출·해석 |

### 🔗 용접 결함 검출 프로젝트

👉 **[WeldVision — welding-defect-detection](https://github.com/hoilycat/welding-defect-detection)**

---

## 📂 프로젝트 구조

```text
welding-annotation-qa/
├── configs/
│   └── taxonomy.yaml          # 6개 결함 클래스와 alias
├── src/welding_qa/
│   ├── models.py              # Polygon과 annotation 모델
│   ├── taxonomy.py            # 라벨 정규화
│   ├── riawelc_reader.py      # JSON 파싱과 검증
│   ├── cvat_converter.py      # CVAT Polygon 양방향 변환
│   ├── cvat_project.py        # CVAT Project 생성·재사용
│   ├── cvat_task.py           # CVAT Task 생성·이미지 업로드
│   └── qa_report.py            # annotation 폴더 QA 집계 리포트
├── tests/
│   ├── fixtures/              # 익명 샘플 JSON
│   ├── test_cvat_converter.py
│   ├── test_cvat_project.py
│   ├── test_cvat_task.py
│   ├── test_qa_report.py
│   ├── test_taxonomy.py
│   └── test_riawelc_reader.py
├── scripts/
│   ├── cvat-local.sh         # macOS/Linux CVAT 환경 관리
│   ├── cvat-local.ps1        # Windows CVAT 환경 관리
│   └── cvat-smoke.sh         # 업로드·동기화·export 통합 검사
└── docs/
    └── project-plan.md        # 다음 단계 로드맵
```

---

## 🚧 다음 단계

- [x] 6개 canonical 결함 taxonomy 정의
- [x] RIAWELC JSON reader 구현
- [x] Polygon 및 modality 기본 검증
- [x] Polygon 면적 및 자기교차 검증
- [x] 익명 fixture와 단위 테스트 구성
- [x] CVAT REST API 연동
- [x] CVAT Project 자동 생성
- [x] CVAT Task 자동 생성과 이미지 업로드
- [x] CVAT annotation 동기화 및 canonical polygon export
- [ ] YOLO/COCO export profile
- [x] 기본 annotation QA 리포트
- [ ] Validation dashboard와 Release Manifest

현재 구현하지 않은 상세 범위와 계획은 [`docs/project-plan.md`](docs/project-plan.md)에서 확인할 수 있습니다.

---

<div align="center">

**깨끗한 라벨이 좋은 모델을 만듭니다.** 🧹✨

</div>
