# COCO·YOLO 내보내기

COCO와 YOLO 내보내기는 같은 taxonomy와 검증 규칙을 사용합니다. 변환 전에 QA 리포트를 만들고 오류를 먼저 해결하는 것을 권장합니다.

## COCO JSON

```bash
python -m welding_qa.coco_export \
  --images data/images \
  --annotations data/annotations \
  --output exports/coco/annotations.json
```

출력에는 다음 정보가 포함됩니다.

- `images`: 파일명, 너비, 높이
- `categories`: canonical defect class
- `annotations`: polygon segmentation, bbox, area, image/category ID

정상 이미지는 `images`에는 포함되지만 결함 annotation은 생성하지 않습니다. `normal`은 배경 상태이므로 COCO defect category에서 제외됩니다.

## YOLO Segmentation

```bash
python -m welding_qa.yolo_export \
  --images data/images \
  --annotations data/annotations \
  --output-dir exports/yolo
```

기본 출력 구조:

```text
exports/yolo/
├── classes.yaml
├── manifest.json
├── images/
└── labels/
    ├── sample.txt
    └── normal.txt
```

각 결함 polygon은 YOLO Segmentation 한 줄로 저장됩니다.

```text
class_id x1 y1 x2 y2 x3 y3 ...
```

좌표는 이미지 너비와 높이를 기준으로 0~1 범위로 정규화됩니다. 정상 이미지는 빈 `.txt` 라벨 파일을 가집니다.

## 클래스 ID

내보내기용 결함 클래스는 다음 순서를 사용합니다.

| COCO ID | YOLO ID | Canonical label |
|---:|---:|---|
| 1 | 0 | `porosity` |
| 2 | 1 | `slag_inclusion` |
| 3 | 2 | `crack` |
| 4 | 3 | `lack_of_fusion` |
| 5 | 4 | `incomplete_penetration` |
| 6 | 5 | `undercut` |

`normal`은 결함 객체가 아니므로 export class ID를 갖지 않습니다. taxonomy 파일의 ID, CVAT 서버의 label ID, COCO/YOLO export ID는 목적이 다르므로 서로 같은 값이라고 가정하면 안 됩니다.

## 출력 안전 규칙

- YOLO 출력 디렉터리가 이미 있으면 실패하여 실수로 데이터셋을 덮어쓰는 일을 막습니다. 새 출력 경로를 사용하세요.
- COCO 출력 파일은 같은 경로를 지정하면 교체되므로 실행 전에 경로를 확인하세요.
- 출력 폴더를 교체하기 전에 원본 이미지와 canonical JSON이 안전한지 확인합니다.
- 생성된 COCO/YOLO 파일은 원본이 아니라 파생 데이터입니다.

## 학습 데이터 분할

내보내기는 형식 변환만 담당하며 train/validation/test 분할을 자동으로 결정하지 않습니다. 같은 용접 시편이나 연속 프레임이 서로 다른 분할에 섞이면 데이터 누수가 생길 수 있으므로, 촬영 단위나 시편 단위를 기준으로 별도의 분할 정책을 적용하세요.
