from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml


class TaxonomyConfig:
    def __init__(self, config_data: dict[str, Any]) -> None:
        self.raw_config = config_data
        self.canonical_classes: dict[str, dict[str, Any]] = config_data.get("canonical_classes", {})
        self.alias_to_canonical: dict[str, str] = {}
        self._build_alias_map()

    @classmethod
    def load_from_yaml(cls, yaml_path: str | Path) -> TaxonomyConfig:
        path = Path(yaml_path)
        if not path.is_file():
            raise FileNotFoundError(f"Taxonomy config file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(data or {})

    def _build_alias_map(self) -> None:
        for slug, meta in self.canonical_classes.items():
            # Add slug itself
            self.alias_to_canonical[slug.lower()] = slug
            
            # Add Korean name
            korean_name = meta.get("korean_name")
            if korean_name:
                self.alias_to_canonical[korean_name.lower().strip()] = slug

            # Add aliases
            for alias in meta.get("aliases", []):
                cleaned = str(alias).lower().strip()
                if cleaned:
                    self.alias_to_canonical[cleaned] = slug

    def get_canonical_slug(self, raw_label: str) -> str:
        if not raw_label:
            raise ValueError("Raw label cannot be empty.")
        cleaned = str(raw_label).lower().strip()
        if cleaned in self.alias_to_canonical:
            return self.alias_to_canonical[cleaned]
        raise ValueError(f"Unknown label '{raw_label}'. Not found in canonical taxonomy aliases.")

    def is_modality_allowed(self, canonical_slug: str, modality: str) -> bool:
        meta = self.canonical_classes.get(canonical_slug)
        if not meta:
            return False
        allowed = meta.get("allowed_modalities", [])
        return modality.upper() in [m.upper() for m in allowed]
