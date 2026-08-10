from pathlib import Path

import pytest
from welding_qa.models import ParsingError
from welding_qa.taxonomy import TaxonomyConfig


@pytest.fixture
def taxonomy_yaml_path() -> Path:
    return Path(__file__).resolve().parents[1] / "configs" / "taxonomy.yaml"


def test_taxonomy_loading(taxonomy_yaml_path: Path):
    taxonomy = TaxonomyConfig.load_from_yaml(taxonomy_yaml_path)
    assert taxonomy is not None
    assert len(taxonomy.canonical_classes) == 6
    assert "porosity" in taxonomy.canonical_classes
    assert "crack" in taxonomy.canonical_classes


def test_porosity_alias_conversion(taxonomy_yaml_path: Path):
    taxonomy = TaxonomyConfig.load_from_yaml(taxonomy_yaml_path)
    
    # Check Korean alias
    assert taxonomy.get_canonical_slug("기공") == "porosity"
    
    # Check uppercase / mixed case
    assert taxonomy.get_canonical_slug("POROSITY") == "porosity"
    assert taxonomy.get_canonical_slug("Porosity") == "porosity"
    
    # Check alternative alias
    assert taxonomy.get_canonical_slug("gas_pore") == "porosity"


def test_unknown_label_raises_error(taxonomy_yaml_path: Path):
    taxonomy = TaxonomyConfig.load_from_yaml(taxonomy_yaml_path)
    with pytest.raises(ValueError, match="Unknown label"):
        taxonomy.get_canonical_slug("non_existent_defect_label_xyz")


def test_packaged_default_taxonomy_matches_repository_config(
    taxonomy_yaml_path: Path,
):
    packaged = TaxonomyConfig.load_default()
    repository = TaxonomyConfig.load_from_yaml(taxonomy_yaml_path)

    assert packaged.raw_config == repository.raw_config


def test_taxonomy_rejects_alias_collision_with_canonical_slug():
    with pytest.raises(ParsingError, match="alias 'porosity' is ambiguous"):
        TaxonomyConfig(
            {
                "canonical_classes": {
                    "porosity": {"aliases": [], "allowed_modalities": ["RT"]},
                    "crack": {
                        "aliases": ["porosity"],
                        "allowed_modalities": ["RT"],
                    },
                }
            }
        )


@pytest.mark.parametrize(
    "config",
    [
        {"canonical_classes": []},
        {"canonical_classes": {"porosity": []}},
        {
            "canonical_classes": {
                "porosity": {"aliases": "gas_pore", "allowed_modalities": ["RT"]}
            }
        },
        {
            "canonical_classes": {
                "porosity": {"aliases": [], "allowed_modalities": "RT"}
            }
        },
    ],
)
def test_taxonomy_rejects_invalid_schema(config: dict[str, object]):
    with pytest.raises(ParsingError, match="Taxonomy"):
        TaxonomyConfig(config)  # type: ignore[arg-type]
