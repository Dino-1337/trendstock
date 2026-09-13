"""Section F/5: trend <-> catalog matching, weighted by category agreement +
brand bonus/conflict (see app/catalog/matching.py's module docstring for the
full design rationale).

Test trends are built from the catalog's own real vendor/type vocabulary
(Nike, Puma, Adidas, sneakers, slides, tshirts - all literal values from
data/fixtures/shopify_products.csv) run through the real rule-based tagger
against the real vendored Shopify vocabulary, not invented one-off phrases
and not a mocked tagging layer - the rule-based tagger is deterministic and
makes no network calls, so there's nothing to mock here.
"""

import pytest

from app.catalog.load_products import DEFAULT_CATALOG_CSV, load_products
from app.catalog.matching import (
    build_brand_vocab,
    match_trends_to_catalog,
    score_trend_product,
)
from app.tagging.product_tagger import _product_text
from app.tagging.rule_based import tag_text
from app.tagging.vocabulary import get_vocabulary


@pytest.fixture(scope="module")
def vocabulary():
    return get_vocabulary()


@pytest.fixture
def catalog(vocabulary):
    # Explicit path: load_products() with no argument now means "whatever the
    # seller uploaded", which is nothing in a test run.
    products = load_products(DEFAULT_CATALOG_CSV)
    for p in products:
        p["category_tags"] = tag_text(_product_text(p), vocabulary).tags
    return products


def make_trend(text, classification="rising", vocabulary=None):
    vocabulary = vocabulary or get_vocabulary()
    return {
        "trend": text,
        "classification": classification,
        "category_tags": tag_text(text, vocabulary).tags,
        "why": [],
    }


def test_naive_bug_nike_sneakers_excludes_puma(catalog, vocabulary):
    """The bug this section fixes: 'nike sneakers' used to match 17 products
    including Puma. It must now match only Nike Sneakers products."""
    trend = make_trend("nike sneakers", vocabulary=vocabulary)
    known_vendors = build_brand_vocab(catalog)
    matches = [
        p for p in catalog
        if score_trend_product(set(trend["category_tags"]), trend["trend"], p, known_vendors) > 0
    ]
    assert matches
    assert all(p["vendor"] == "Nike" for p in matches)
    assert all(p["product_type"] == "sneakers" for p in matches)


def test_naive_bug_puma_slides_excludes_wrong_brand_and_wrong_type(catalog, vocabulary):
    """'puma slides' must not match Puma Sneakers (wrong type) or Converse
    Slides (wrong brand)."""
    trend = make_trend("puma slides", vocabulary=vocabulary)
    known_vendors = build_brand_vocab(catalog)
    matches = [
        p for p in catalog
        if score_trend_product(set(trend["category_tags"]), trend["trend"], p, known_vendors) > 0
    ]
    assert matches
    assert all(p["vendor"] == "Puma" and p["product_type"] == "slides" for p in matches)


def test_brand_agreement_outscores_no_brand_which_outscores_conflict(catalog, vocabulary):
    """The user's own example: an Adidas trend against a Nike product sharing
    the Sneakers category is WEAKER evidence than a trend naming no brand at
    all, not neutral - and brand agreement is stronger still."""
    known_vendors = build_brand_vocab(catalog)
    nike_sneaker = next(p for p in catalog if p["vendor"] == "Nike" and p["product_type"] == "sneakers")

    brand_agree = make_trend("nike sneakers", vocabulary=vocabulary)
    no_brand = make_trend("summer sneakers restock this week", vocabulary=vocabulary)
    brand_conflict = make_trend("adidas sneakers restock", vocabulary=vocabulary)

    score_agree = score_trend_product(
        set(brand_agree["category_tags"]), brand_agree["trend"], nike_sneaker, known_vendors)
    score_none = score_trend_product(
        set(no_brand["category_tags"]), no_brand["trend"], nike_sneaker, known_vendors)
    score_conflict = score_trend_product(
        set(brand_conflict["category_tags"]), brand_conflict["trend"], nike_sneaker, known_vendors)

    assert score_agree > score_none > score_conflict
    # Brand conflict must still net to a full exclusion, preserving the
    # original gate behaviour ("nike sneakers" must not match Puma products)
    # under the new weighted scheme.
    assert score_conflict == 0.0


def test_no_category_signal_is_never_a_match(catalog, vocabulary):
    """A trend naming this product's brand but no recognisable commerce
    category at all must not match - category agreement is required, brand
    alone is not enough."""
    known_vendors = build_brand_vocab(catalog)
    nike_sneaker = next(p for p in catalog if p["vendor"] == "Nike" and p["product_type"] == "sneakers")
    trend = make_trend("Nike quarterly earnings report beats estimates", vocabulary=vocabulary)
    assert trend["category_tags"] == []  # sanity: genuinely no category tag here
    score = score_trend_product(set(trend["category_tags"]), trend["trend"], nike_sneaker, known_vendors)
    assert score == 0.0


def test_irrelevant_trend_matches_nothing(catalog):
    """A trend with zero commerce-relevant tags (normally caught upstream by
    the relevance gate, see app/tagging/relevance.py) still safely matches
    nothing if one ever reaches this layer directly."""
    trend = {"trend": "state election results", "classification": "new", "category_tags": [], "why": []}
    products, gaps, match_counts = match_trends_to_catalog([trend], [dict(p) for p in catalog])
    assert all(not p["matched_trends"] for p in products)
    assert match_counts[trend["trend"]] == 0
    assert len(gaps) == 1


def test_category_only_match_spans_every_brand_in_that_category(catalog, vocabulary):
    """Honest limitation, documented in matching.py's module docstring: with
    only brand+type data, a trend naming a category but no brand matches
    every product in that category equally, regardless of brand - there is
    nothing in this catalog for a style word to bind to."""
    trend = make_trend("sneakers trending everywhere this week", vocabulary=vocabulary)
    products, gaps, match_counts = match_trends_to_catalog([trend], [dict(p) for p in catalog])
    matched_vendors = {p["vendor"] for p in products if p["matched_trends"]}
    matched_types = {p["product_type"] for p in products if p["matched_trends"]}
    assert len(matched_vendors) > 1
    assert matched_types == {"sneakers"}


def test_gap_when_trend_category_absent_from_catalog(catalog, vocabulary):
    """A genuinely commerce-relevant trend (real Shopify category) that this
    sneakers/tshirts/slides catalog simply doesn't sell anything in - the gap
    path, driven by real vocabulary rather than an invented placeholder."""
    trend = make_trend("claw clips restocking fast this week", vocabulary=vocabulary)
    assert trend["category_tags"]  # it IS commerce-relevant (real category: Claw Clips)
    products, gaps, match_counts = match_trends_to_catalog([trend], [dict(p) for p in catalog])
    assert all(not p["matched_trends"] for p in products)
    assert len(gaps) == 1
    assert gaps[0]["trend"] == trend["trend"]
