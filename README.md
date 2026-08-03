# welding-annotation-qa (v0.1)

CVAT 기반 용접 어노테이션 데이터 QA 및 정제 파이프라인 프로젝트입니다.

---

## 🎯 1. 프로젝트 목적
* 원시 용접 비파괴검사(RT/VT) 어노테이션 데이터셋의 품질 검증(QA), 스키마 정규화 및 표준 Taxonomy 매핑을 자동화합니다.
* 다수의 어노테이터 및 원시 라벨링 출처에서 발생하는 데이터 오류(좌표 이탈, 라벨 오기, 배열 불일치)를 사전 검출합니다.

---

## 🔄 2. WeldVision과의 관계 (Producer - Consumer)
* **`welding-annotation-qa` (Producer / Upstream)**:
  - 원시 Polygon JSON 어노테이션의 품질 검증, 라벨 정규화, 정제된 캐노니컬 데이터셋 생성 및 릴리스 관리를 전담합니다.
* **`WeldVision` (Consumer / Downstream)**:
  - QA가 완료되어 릴리스된 결함 데이터셋을 소비하여 2단계(YOLOv8 + C++/OpenCV) 학습, 추론 및 Gradio 대시보드 시연을 담당합니다.

---

## 📋 3. v0.1 개발 범위 및 현재 상태

### 🟢 포함 범위 (v0.1)
1. **Canonical Taxonomy 설정 (`configs/taxonomy.yaml`)**:
   - 6대 결함 클래스 슬러그, 한국어 명칭, RT/VT 모달리티 허용 정책 및 Alias 매핑 테이블.
2. **원시 RIAWELC JSON 리더 (`src/welding_qa/riawelc_reader.py`)**:
   - 필수 필드 파싱, Polygon x/y 좌표 길이 검증 및 Canonical Alias 변환.
3. **익명화 Fixture 및 단위 테스트 스위트 (`tests/`)**:
   - 개인정보 제거 샘플어노테이션 Fixture 및 Pytest 검증.

### 🔴 제외 범위 (Current Out of Scope)
- CVAT API 연동 및 Project/Task 자동 생성
- 원본 이미지/JSON 전체 수집 및 복사
- YOLO 모델 학습, 추론 및 Split 생성
- 통계 대시보드 및 DVC 연동

### 📍 현재 상태 (Current Status)
> **[Pre-CVAT Integration Status]**
> 현재 v0.1 단계는 외부 CVAT API 연동 및 원본 이미지 수집 전 단계로, 로컬 환경에서 파싱 스키마와 Taxonomy 매핑 규칙의 안정성을 검증하는 단계입니다.

---

## 📐 4. 예상 데이터 흐름 (Data Pipeline Flow)

```text
[ 원시 Polygon JSON / Images ]
              │
              ▼
[ welding-annotation-qa (v0.1) ]
  ├── Schema Validation (riawelc_reader)
  └── Canonical Taxonomy Normalization (taxonomy.yaml)
              │
              ▼
[ Verified Canonical Annotation Release ]
              │
              ▼
[ WeldVision (YOLO Training & Gradio App) ]
```
