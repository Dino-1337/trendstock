"""Product tagger (app/tagging/product_tagger.py): tags derived from the
catalog's own fields, no hardcoded product knowledge. Uses the real
rule-based path (conftest.py forces GROQ_API_KEY unset for all tests, so
this never touches the network) and a tmp cache dir to avoid touching the
real disk cache namespace.
"""

from app.tagging import tagger
from app.tagging.product_tagger import _product_text, tag_products
from app.tagging.vocabulary import get_vocabulary


def test_product_text_blob_includes_all_fields():
    product = {
        "title": "Nike Sneakers 0", "product_type": "sneakers",
        "vendor": "Nike", "tags": ["nike", "sneakers"],
    }
    blob = _product_text(product)
    assert "Nike Sneakers 0" in blob
    assert "sneakers" in blob
    assert "Nike" in blob


def test_tag_products_is_dynamic_across_different_catalogs(tmp_path, monkeypatch):
    """A different uploaded CSV must produce different tags with zero code
    changes - here, a jewelry catalog that shares no vocabulary with the
    sneakers/tshirts/slides sample catalog."""
    monkeypatch.setattr(tagger, "CACHE_DIR", tmp_path)  # not required (tag_products doesn't take cache_dir) but harmless

    vocabulary = get_vocabulary()
    sneaker_catalog = [
        {"product_id": "p1", "title": "Nike Sneakers 0", "product_type": "sneakers",
         "vendor": "Nike", "tags": ["nike", "sneakers"]},
    ]
    jewelry_catalog = [
        {"product_id": "p2", "title": "Silver Rings Set", "product_type": "rings",
         "vendor": "Acme", "tags": ["rings", "silver"]},
    ]

    sneaker_results = tag_products(sneaker_catalog, vocabulary)
    jewelry_results = tag_products(jewelry_catalog, vocabulary)

    assert sneaker_results["p1"].tags == ["Sneakers"]
    assert jewelry_results["p2"].tags == ["Rings"]
