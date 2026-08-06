"""여러 이름으로 들어오는 결함 라벨을 canonical taxonomy로 정규화하는 모듈."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml


class TaxonomyConfig:
    """YAML taxonomy 설정과 빠른 alias 조회표를 함께 관리하는 클래스."""

    def __init__(self, config_data: dict[str, Any]) -> None:
        """원본 설정을 보존하고 라벨 정규화에 사용할 alias 조회표를 준비하는 함수."""
        self.raw_config = config_data
        self.canonical_classes: dict[str, dict[str, Any]] = config_data.get("canonical_classes", {})
        self.alias_to_canonical: dict[str, str] = {}
        self._build_alias_map()

    @classmethod
    def load_from_yaml(cls, yaml_path: str | Path) -> TaxonomyConfig:
        """UTF-8 YAML 파일을 읽어 TaxonomyConfig 객체로 만드는 함수."""
        path = Path(yaml_path)
        if not path.is_file():
            raise FileNotFoundError(f"Taxonomy config file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(data or {})

    def _build_alias_map(self) -> None:
        """canonical slug와 모든 표시 이름을 소문자 alias 조회표로 펼치는 함수."""
        # canonical slug, 한국어 이름, 추가 alias를 모두 같은 조회표에 넣는 코드
        for slug, meta in self.canonical_classes.items():
            # canonical slug 자체도 대소문자 구분 없이 조회할 수 있게 등록하는 코드
            self.alias_to_canonical[slug.lower()] = slug

            # 사람이 입력하는 한국어 이름을 canonical slug에 연결하는 코드
            korean_name = meta.get("korean_name")
            if korean_name:
                self.alias_to_canonical[korean_name.lower().strip()] = slug

            # 데이터셋마다 다른 영문·축약 alias를 공백 제거 후 등록하는 코드
            for alias in meta.get("aliases", []):
                cleaned = str(alias).lower().strip()
                if cleaned:
                    self.alias_to_canonical[cleaned] = slug

    def get_canonical_slug(self, raw_label: str) -> str:
        """원본 라벨을 canonical slug로 변환하거나 알 수 없는 라벨을 거부하는 함수."""
        # 앞뒤 공백과 영문 대소문자 차이를 제거해 데이터셋별 표기 흔들림을 흡수
        if not raw_label:
            raise ValueError("Raw label cannot be empty.")
        cleaned = str(raw_label).lower().strip()
        if cleaned in self.alias_to_canonical:
            return self.alias_to_canonical[cleaned]
        raise ValueError(f"Unknown label '{raw_label}'. Not found in canonical taxonomy aliases.")

    def is_modality_allowed(self, canonical_slug: str, modality: str) -> bool:
        """결함 종류가 주어진 RT/VT 검사 방식에서 허용되는지 확인하는 함수."""
        # taxonomy에 없는 slug는 허용하지 않는 보수적인 기본 정책
        meta = self.canonical_classes.get(canonical_slug)
        if not meta:
            return False
        allowed = meta.get("allowed_modalities", [])
        # 설정과 입력 모두 대문자로 맞춰 RT/VT의 대소문자 차이를 무시
        return modality.upper() in [m.upper() for m in allowed]
