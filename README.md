<div align="center">

# 🔥 welding-annotation-qa

### 용접 결함 라벨을 가지런히 정리하는 데이터 QA 도구

![version](https://img.shields.io/badge/version-0.1-E76F51?style=flat-square)
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

> 📍 현재 버전은 **v0.1**입니다.<br>
> JSON 검증과 라벨 정규화에 집중하며 CVAT 연동과 dataset export는 아직 준비 중입니다.

---

## ✨ v0.1에서 할 수 있는 일

| 기능 | 하는 일 |
|---|---|
| 🏷️ 라벨 정규화 | `기공`, `POROSITY`, `gas_pore`를 `porosity`로 통일 |
| 📐 Polygon 검사 | x/y 좌표 개수와 최소 꼭짓점 수 확인 |
| 🚨 오류 감지 | 올바르지 않은 annotation 항목을 즉시 알림 |
| 🩻 검사 방식 확인 | 결함별 RT/VT modality 허용 여부 검증 |
| 🖼️ 메타데이터 보존 | `image_id`, `filename`, `width`, `height` 유지 |
| 🌱 정상 이미지 허용 | 결함이 없는 `annotations: []`도 정상 처리 |

입력은 다음 세 가지 형태를 지원합니다.

- JSON 파일 경로
- JSON 문자열
- Python dictionary

JSON의 annotation 목록 이름은 `annotations`, `shapes`, `objects` 중 하나를 사용할 수 있습니다.

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

Docker Desktop을 실행한 뒤 아래 명령으로 프로젝트에 고정된 CVAT 버전을
준비하고 시작할 수 있습니다.

```bash
cp .env.cvat.example .env.cvat
./scripts/cvat-local.sh bootstrap
./scripts/cvat-local.sh up
```

CVAT는 기본적으로 <http://localhost:8080>에서 열립니다. 최초 관리자 계정은
서버가 준비된 다음 대화형 명령으로 생성합니다.

```bash
./scripts/cvat-local.sh health
./scripts/cvat-local.sh superuser
```

Python SDK가 필요한 개발 환경은 서버와 같은 2.70 버전으로 설치됩니다.

```bash
pip install -e ".[dev,cvat]"
```

상태 확인과 종료에는 다음 명령을 사용합니다. `down`은 Docker 데이터 볼륨을
삭제하지 않으므로 생성한 사용자와 annotation이 유지됩니다.

```bash
./scripts/cvat-local.sh status
./scripts/cvat-local.sh down
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
│   └── cvat_converter.py      # CVAT Polygon 양방향 변환
├── tests/
│   ├── fixtures/              # 익명 샘플 JSON
│   ├── test_cvat_converter.py
│   ├── test_taxonomy.py
│   └── test_riawelc_reader.py
└── docs/
    └── project-plan.md        # 다음 단계 로드맵
```

---

## 🚧 다음 단계

- [x] 6개 canonical 결함 taxonomy 정의
- [x] RIAWELC JSON reader 구현
- [x] Polygon 및 modality 기본 검증
- [x] 익명 fixture와 단위 테스트 구성
- [ ] CVAT REST API 연동
- [ ] CVAT Project/Task 자동 생성
- [ ] YOLO/COCO export profile
- [ ] QA 리포트와 validation dashboard

현재 구현하지 않은 상세 범위와 계획은 [`docs/project-plan.md`](docs/project-plan.md)에서 확인할 수 있습니다.

---

<div align="center">

**깨끗한 라벨이 좋은 모델을 만듭니다.** 🧹✨

</div>
