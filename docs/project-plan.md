# Project Plan & Roadmap: welding-annotation-qa

## 🎯 Vision
CVAT 기반 용접 어노테이션 데이터셋의 품질 검증, 표준 Taxonomy 정규화 및 정제 릴리스 파이프라인 구축.

---

## 🛣️ Milestones

### Phase 1: v0.1 Kickoff & Foundation (Complete)
- [x] Sibling 프로젝트 구조 초기화 (`welding-annotation-qa`)
- [x] Canonical Taxonomy YAML 정의 (6대 결함 슬러그, Korean Labels, Aliases)
- [x] Raw RIAWELC JSON Reader 스키마 파서 및 x/y 좌표 검증기 구현
- [x] 익명화 샘플 Fixture 및 Pytest 단위 테스트 스위트 구축

### Phase 2: CVAT Integration & Task Curation (Complete)
- [x] CVAT REST API SDK 연동 모듈 개발
- [x] Canonical taxonomy 기반 Project 자동 등록
- [x] Task 자동 등록 및 어노테이션 동기화 파이프라인
- [x] Raw JSON ↔ CVAT Polygon 2-way 변환 서브시스템

### Phase 3: Automated QA & Validation Dashboard (Upcoming)
- [ ] Bounding Box / Polygon 경계 이탈 및 레이블 충돌 자동 검수기
- [ ] Duplicate Image Detection (Perceptual Hashing)
- [ ] QA Validation Dashboard 및 Release Manifest 릴리스 연동
