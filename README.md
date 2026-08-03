# welding-annotation-qa

여러 출처에서 만들어진 **용접 결함 Polygon JSON을 검사하고, 서로 다른 라벨을 하나의 표준 이름으로 정리하는 Python 도구**입니다.

예를 들어 `기공`, `POROSITY`, `gas_pore`처럼 서로 다르게 작성된 라벨을 모두 `porosity`로 변환합니다. Polygon 좌표가 올바른지 확인하고, RT/VT 검사 방식에 허용된 결함인지도 검증합니다.

> 현재 버전은 **v0.1**입니다. JSON 검증과 라벨 정규화에 집중하며, CVAT API 연동과 데이터셋 export는 아직 포함하지 않습니다.

## 이 저장소가 하는 일

용접 데이터는 작업자나 데이터 출처에 따라 라벨 이름과 JSON 구조가 달라질 수 있습니다. 이 저장소는 모델 학습 전에 데이터를 한 번 검사하여 다음 문제를 찾거나 정리합니다.

- `기공`, `porosity`, `gas_pore`와 같은 라벨 표현 통일
- Polygon의 x/y 좌표 개수 불일치 검출
- 꼭짓점이 3개보다 적은 잘못된 Polygon 검출
- 올바르지 않은 annotation 항목 검출
- 결함 클래스별 RT/VT modality 허용 여부 확인
- 이미지 식별자와 크기 메타데이터 보존

## v0.1 지원 범위

- `annotations`, `shapes`, `objects` 목록을 사용하는 JSON 읽기
- 파일 경로, JSON 문자열 또는 Python dictionary 입력
- 6개 canonical 결함 클래스와 alias 매핑
- Polygon 기본 구조 검증
- RT/VT modality 정책 검증
- `image_id`, `filename`, `width`, `height` 메타데이터 보존

Canonical taxonomy는 [`configs/taxonomy.yaml`](configs/taxonomy.yaml)에서 관리합니다.

| Canonical label | 한글 이름 |
|---|---|
| `porosity` | 기공 |
| `slag_inclusion` | 슬래그 혼입 |
| `crack` | 균열 |
| `lack_of_fusion` | 융합 불량 |
| `incomplete_penetration` | 용입 부족 |
| `undercut` | 언더컷 |

## 빠르게 실행하기

Python 3.10 이상이 필요합니다.

```bash
pip install -e ".[dev]"
pytest
```

Python 코드에서는 다음과 같이 사용할 수 있습니다.

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

결함이 없는 정상 이미지는 `"annotations": []`로 표현할 수 있으며, 이 경우 빈 목록을 반환합니다.

## 데이터 흐름

```text
[원본 이미지 + Polygon JSON]
              ↓
[welding-annotation-qa]
  - JSON 구조와 Polygon 검사
  - 라벨을 canonical taxonomy로 변환
  - modality와 메타데이터 확인
              ↓
[검증된 DefectAnnotation 목록]
              ↓
[모델 학습 및 검출 프로젝트]
```

## WeldVision과의 관계

이 저장소는 **학습 전에 어노테이션을 검사하고 정리하는 역할**을 담당합니다. 정리된 데이터를 사용해 모델을 학습하고 용접 결함을 검출·해석하는 작업은 WeldVision에서 진행합니다.

- WeldVision: <https://github.com/hoilycat/welding-defect-detection>

쉽게 구분하면 다음과 같습니다.

- `welding-annotation-qa`: 데이터가 올바른지 검사하고 라벨을 통일
- `WeldVision`: 정리된 데이터로 모델을 학습하고 결함을 검출·해석

## 아직 지원하지 않는 기능

- CVAT REST API 연동
- CVAT Project/Task 자동 생성
- 전체 이미지와 JSON 수집 또는 복사
- YOLO/COCO 형식 export와 dataset split 생성
- 모델 학습 및 추론
- QA 대시보드와 DVC 연동

향후 계획은 [`docs/project-plan.md`](docs/project-plan.md)에서 확인할 수 있습니다.
