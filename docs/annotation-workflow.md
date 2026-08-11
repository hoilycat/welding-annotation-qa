# 어노테이션 작업 흐름

이 문서는 RIAWELC JSON을 검사하고 CVAT Project/Task로 옮기거나 다시 내려받는 흐름을 설명합니다. 명령은 저장소 루트에서 실행합니다.

## 입력 형식

결함 이미지는 `labels`에 하나 이상의 polygon을 가집니다.

```json
{
  "version": "1.0",
  "modality": "RT",
  "image_info": {
    "image_id": "SAMPLE_0001",
    "filename": "sample.png",
    "width": 1280,
    "height": 720
  },
  "annotations": [
    {
      "annotation_id": "ANN_001",
      "label": "슬래그",
      "polygon": {
        "x": [100, 180, 190, 110],
        "y": [120, 115, 170, 175]
      }
    }
  ]
}
```

정상 이미지는 빈 `annotations` 목록을 사용합니다.

```json
{
  "version": "1.0",
  "modality": "RT",
  "image_info": {
    "image_id": "NORMAL_0001",
    "filename": "normal.png",
    "width": 1280,
    "height": 720
  },
  "annotations": []
}
```

일부 원본 RIAWELC 파일의 `class: "normal"` 항목도 읽을 수 있지만, 내부에서는 결함 polygon으로 만들지 않습니다.

## Python에서 파싱하기

```python
from pathlib import Path

from welding_qa import TaxonomyConfig, parse_riawelc_json

taxonomy = TaxonomyConfig.load_from_yaml(Path("configs/taxonomy.yaml"))
annotations = parse_riawelc_json(Path("annotation.json"), taxonomy)

for annotation in annotations:
    print(annotation.label_original, annotation.label_canonical)
```

파서는 라벨 별칭을 canonical label로 바꾸고 필수 필드, 이미지 크기, 좌표 범위, polygon 구조를 검사합니다.

## QA 리포트 만들기

```bash
python -m welding_qa.qa_report \
  --annotations data/annotations \
  --output reports/qa-report.json
```

Windows PowerShell에서는 한 줄로 실행하거나 줄 끝의 `\` 대신 백틱을 사용합니다.

```powershell
python -m welding_qa.qa_report --annotations data/annotations --output reports/qa-report.json
```

리포트에는 검사한 파일 수, 정상 파일 수, 오류 파일과 구체적인 원인이 기록됩니다. CVAT 업로드나 내보내기 전에 이 검사를 먼저 실행하는 것이 좋습니다.

## CVAT용 polygon payload

```python
from pathlib import Path

from welding_qa import TaxonomyConfig, annotations_to_cvat_shapes, parse_riawelc_json

taxonomy = TaxonomyConfig.load_from_yaml(Path("configs/taxonomy.yaml"))
annotations = parse_riawelc_json(Path("annotation.json"), taxonomy)

shapes = annotations_to_cvat_shapes(
    annotations,
    {"slag_inclusion": 17},
    frame=0,
)
```

CVAT 업로드용 `label_id`는 CVAT 서버에서 생성된 ID입니다. taxonomy의 고정 ID와 혼동하지 마세요.

## 환경 변수 불러오기

```bash
# macOS / Linux
set -a
source .env.cvat
set +a
```

```powershell
# Windows PowerShell
Get-Content .env.cvat | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
    }
}
```

## CVAT Project 생성 또는 재사용

```bash
python -m welding_qa.cvat_project \
  --modality RT \
  --name "Welding Defects"
```

같은 이름의 호환 가능한 Project가 있으면 재사용합니다. taxonomy와 맞지 않는 Project는 자동으로 덮어쓰지 않습니다.

## CVAT Task 생성과 업로드

```bash
python -m welding_qa.cvat_task \
  --modality RT \
  --images data/images \
  --annotations data/annotations \
  --project-name "Welding Defects" \
  --task-name "batch-001"
```

Task 생성 과정은 다음 순서로 진행됩니다.

1. JSON 파싱과 canonical label 정규화
2. 이미지 파일과 크기 확인
3. CVAT Project 및 label ID 확인
4. 이미지 업로드
5. polygon 어노테이션 업로드

정상 이미지는 프레임은 생성하지만 polygon shape는 만들지 않습니다.

## CVAT 어노테이션 동기화

CVAT에서 수정한 어노테이션을 canonical JSON으로 내려받습니다.

```bash
python -m welding_qa.cvat_task \
  --modality RT \
  --images data/images \
  --task-name "batch-001" \
  --export-annotations data/synced
```

프레임 이름을 기준으로 기존 JSON과 연결합니다. 서버 프레임과 로컬 이미지가 일치하지 않으면 기본적으로 실패합니다. 일부 이미지만 annotation JSON을 가진 입력을 의도적으로 올릴 때는 `--allow-missing-annotations`를 사용할 수 있습니다. 이미지와 매칭되지 않는 JSON은 이 옵션으로도 허용하지 않습니다.

기존 Task에 annotation이 있으면 작업자 데이터를 보호하기 위해 업로드를 거부합니다. native backup을 만든 뒤 `--annotations`와 `--replace-annotations`를 함께 지정해야 교체할 수 있습니다.

## CVAT native backup

CVAT Project 또는 Task를 그대로 복원하려면 native backup을 별도로 보관합니다. canonical JSON은 검토와 변환에 적합하지만 사용자, 작업 상태, 일부 CVAT 메타데이터까지 완전히 보존하지는 않습니다.

권장 보관 순서:

1. CVAT native backup
2. canonical JSON
3. 원본 이미지
4. QA 리포트
5. 필요 시 COCO/YOLO 파생 데이터셋

COCO와 YOLO 출력은 언제든 canonical JSON에서 다시 만들 수 있으므로 원본보다는 파생 산출물로 취급합니다.
