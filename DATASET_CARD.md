# Dataset Card: Welding Defect Annotation QA

## 📌 Data Summary
- **Dataset Name**: Welding Defect Inspection & Annotation QA Dataset
- **Domain**: Radiographic Testing (RT) & Visual Testing (VT) Welding Inspection
- **Ground Truth Standard**: Polygon JSON Annotation (Canonical Standard)
- **Reference Legacy Artifact**: `weldvision-yolo-reference-2026-08-03.zip` (YOLO formatted reference baseline)

---

## 🏷️ Canonical Defect Taxonomy

| Canonical Slug | Korean Name | Allowed Modalities | Description |
| :--- | :--- | :---: | :--- |
| `porosity` | 기공 | `[RT, VT]` | 용접부 내부 또는 표면에 형성된 기공 결함 |
| `slag_inclusion` | 슬래그 혼입 | `[RT, VT]` | 용접 금속 내부에 잔류된 비금속 슬래그 |
| `crack` | 균열 | `[RT, VT]` | 용접재 또는 열영향부에 발생한 선형 균열 |
| `lack_of_fusion` | 융합 불량 | `[RT, VT]` | 모재와 용접금속 간 불완전 융합 |
| `incomplete_penetration` | 용입 부족 | `[RT, VT]` | 용접 루트부 완전 용입 미달 |
| `undercut` | 언더컷 | `[RT, VT]` | 모재 침식으로 형성된 홈 결함 |

---

## ⚠️ Ground Truth Policy Notice
1. **Canonical Primary Standard**: 모든 데이터 품질 검수 및 재변환의 유일한 기준 데이터(Canonical Ground Truth)는 원본 Polygon JSON 어노테이션입니다.
2. **Dynamic Class ID Mapping**: 숫자 클래스 ID(0, 1, 2...)는 Canonical 단계에 고정되지 않으며, 타겟 모델(YOLO, COCO 등)의 Export Profile에 맞춰 동적으로 매핑됩니다.
