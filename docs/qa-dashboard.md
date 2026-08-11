# QA 대시보드와 Release Manifest

Phase 3 QA는 단일 JSON의 구조뿐 아니라 데이터셋 전체의 관계를 함께 검사합니다. 결과는 자동화용 JSON 두 개와 브라우저에서 바로 여는 정적 HTML 대시보드로 저장됩니다.

## 실행

저장소 루트에서 다음 명령을 실행합니다.

```bash
python -m welding_qa.release_report \
  --images data/images \
  --annotations data/annotations \
  --modality RT \
  --output-dir reports/release-001
```

Windows PowerShell에서는 한 줄로 실행할 수 있습니다.

```powershell
python -m welding_qa.release_report --images data\images --annotations data\annotations --modality RT --output-dir reports\release-001
```

완료 후 대시보드를 엽니다.

```bash
# macOS
open reports/release-001/dashboard.html

# Windows PowerShell
Start-Process reports\release-001\dashboard.html
```

기존 출력 폴더는 덮어쓰지 않습니다. 재검사할 때는 새 릴리스 이름을 사용하세요.

## 생성 파일

| 파일 | 용도 |
|---|---|
| `qa-report.json` | 기존 파일별 파싱·taxonomy 검사 결과 |
| `release-manifest.json` | 검사 조건, 요약, 이슈, 파일 checksum과 dataset digest |
| `dashboard.html` | 외부 서버 없이 열 수 있는 검토 화면 |
| `thumbnails/` | 유사 이미지 후보가 있을 때만 만드는 좌우 비교용 축소 이미지 |

manifest와 QA 리포트에는 로컬 드라이브·사용자 폴더의 실제 경로를 남기지 않고 `<images>`, `<annotations>`로 가립니다. 썸네일은 검토 후보만 최대 640×360으로 축소하며 원본 이미지를 변경하지 않습니다.

## 자동 검사 항목

### Annotation 충돌과 중첩

- 서로 다른 라벨이 지정 비율 이상 겹치면 `label_conflict`
- 같은 라벨이 거의 일치하면 `possible_duplicate_annotation`
- 같은 라벨이 일부 겹치면 `annotation_overlap`

Polygon 교차는 Pillow 마스크로 계산합니다. 매우 큰 Polygon은 메모리 사용을 제한하기 위해 비율을 유지한 채 축소하므로 IoU는 검토 후보를 찾기 위한 근삿값입니다. 결과만으로 annotation을 자동 삭제하지 않습니다.

### 중복 이미지

- SHA-256이 같으면 `exact_duplicate`
- SHA-256은 다르지만 perceptual hash가 가까우면 `perceptual_duplicate`
- 평균 밝기 차이를 함께 제한하여 관계없는 균일 이미지를 줄입니다.

Perceptual hash는 검토 후보를 좁히는 도구입니다. 촬영 조건이 비슷한 용접 영상은 실제로 다른 이미지여도 유사하게 판단될 수 있으므로 사람이 최종 확인해야 합니다.
대시보드는 고유 후보 이미지 수와 비교 쌍 수를 나누어 표시하고 각 쌍을 좌우 썸네일로 보여줍니다.

### Dataset 대응 관계

- 이미지와 같은 stem의 JSON이 없으면 `missing_annotation`
- JSON과 같은 stem의 이미지가 없으면 `missing_image`
- 같은 stem이 중복되면 별도 오류로 기록

정상 이미지도 누락과 구별할 수 있도록 `annotations: []`가 있는 JSON을 준비합니다.

## 결과 상태

| 상태 | 의미 |
|---|---|
| `passed` | 파싱 오류, 대응 오류, 검토 후보가 없음 |
| `review` | 충돌·중첩 또는 중복 후보가 있어 사람의 확인이 필요함 |
| `failed` | 잘못된 JSON, 읽을 수 없는 이미지, 이미지·JSON 대응 오류가 있음 |

`review`는 자동 삭제나 실패를 의미하지 않습니다. `failed` 상태에서는 데이터 릴리스 전에 오류를 먼저 해결해야 합니다.

## 임계값 조정

```bash
python -m welding_qa.release_report \
  --images data/images \
  --annotations data/annotations \
  --output-dir reports/release-strict \
  --overlap-threshold 0.05 \
  --duplicate-annotation-iou 0.85 \
  --perceptual-distance 6
```

- `--overlap-threshold`: 작은 값일수록 더 작은 겹침도 표시
- `--duplicate-annotation-iou`: 같은 라벨을 중복 후보로 보는 IoU 기준
- `--perceptual-distance`: 큰 값일수록 더 넓은 범위의 유사 이미지를 표시

## 대시보드 디자인

현재 화면은 WeldVision의 어두운 방사선 판독 UI와 빨강·주황 강조색을 참고한 임시 테마입니다. HTML 구조와 manifest 형식은 디자인과 분리되어 있으므로 이후 UI를 변경해도 검수 결과와 CLI는 그대로 유지됩니다.
