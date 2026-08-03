# References & Baseline Datasets

## 📌 Ground Truth Policy
1. **Canonical Ground Truth**: 원본 이미지 및 원본 Polygon JSON 어노테이션이 모든 검수 및 QA 파이프라인의 유일한 기준 데이터(Canonical Ground Truth)입니다.
2. **Legacy YOLO Reference Artifacts**:
   - `weldvision-yolo-reference-2026-08-03.zip`: 과거 WeldVision 파이프라인에서 추출된 YOLO 포맷 라벨 및 설정 보관용 산출물입니다.
   - 본 ZIP 파일은 파생 산출물 포맷 비교 및 역사적 재현 용도로만 참조되며, 캐노니컬 데이터의 기준이 아닙니다.

---

## ⛔ Git Commit Policy Notice
> **[중요] 대용량 미디어 파일, 원본 데이터셋 및 ZIP 압축 파일은 Git 저장소에 커밋하지 않습니다.**
> 해당 파일들은 `.gitignore`에 등록되어 배제되며, 필요 시 로컬 환경의 외부 데이터 디렉터리(`configs/source.yaml`) 경로를 통해 참조해야 합니다.
