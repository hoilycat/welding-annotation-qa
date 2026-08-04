from pathlib import Path

import pytest
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
