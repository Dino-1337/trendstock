"""Product enrichment. The LLM tier is always stubbed; the rule-based floor
and the persistence layer are exercised for real."""

import pytest
from pydantic import ValidationError

from app.enrichment import product_enricher as pe
from app.enrichment.models import (
    Audience,
    PriceTier,
    ProductEnrichmentBatchLLM,
    ProductEnrichmentLLM,
)
from app.llm import client as llm
from app.storage import db

FINGERPRINT = "fp-test"


def product(pid="p1", title="Banarasi Silk Saree", ptype="saree",
            price=8990.0, tags=("saree", "silk"), vendor="Kalanidhi"):
    return {"product_id": pid, "title": title, "product_type": ptype,
            "price": price, "tags": list(tags), "vendor": vendor}


CATALOG = [
    product("p1", "Banarasi Silk Saree", "saree", 8990.0),
    product("p2", "Chikankari Kurti", "kurti", 1499.0, tags=("kurti", "cotton")),
    product("p3", "Bandhani Dupatta", "dupatta", 999.0, tags=("dupatta",)),
]


def batch_response(per_index):
    """Build a batch response from {index: payload}. Takes a dict positionally
    rather than **kwargs, because integer keys are not valid keyword names."""
    return ProductEnrichmentBatchLLM(products={
        str(i): ProductEnrichmentLLM(**payload) for i, payload in per_index.items()
    })


@pytest.fixture
def conn(tmp_path):
    connection = db.init_db(db.connect(tmp_path / "t.db"))
    yield connection
    connection.close()


@pytest.fixture
def no_llm(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: False)


@pytest.fixture
def stub_llm(monkeypatch):
    """LLM returns a fixed enrichment for index 0 of every batch."""
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(pe, "_enrich_batch_llm", lambda *a, **k: batch_response(
        {0: {"occasions": ["Diwali"], "materials": ["Silk"],
             "audience": "women", "style_descriptors": ["Handloom"]}}
    ))


# --- rule-based floor -----------------------------------------------------

def test_categories_come_from_the_deterministic_tagger(no_llm):
    records = pe.enrich_products(CATALOG)
    assert "Saris" in records[0].categories


def test_every_product_is_returned_even_without_an_llm(no_llm):
    assert len(pe.enrich_products(CATALOG)) == 3


def test_source_records_that_no_model_ran(no_llm):
    assert all(r.source == "rule_based" for r in pe.enrich_products(CATALOG))


def test_empty_catalog_returns_nothing(no_llm):
    assert pe.enrich_products([]) == []


def test_use_llm_false_skips_the_model(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(pe, "_enrich_batch_llm",
                        lambda *a, **k: pytest.fail("must not call the model"))
    assert pe.enrich_products(CATALOG, use_llm=False)[0].source == "rule_based"


# --- price tiers ----------------------------------------------------------

def test_price_tiers_are_relative_to_this_catalog(no_llm):
    # A fixed rupee threshold would mislabel both a premium saree store and a
    # budget kurti store; tiers are quantiles of the catalog itself.
    tiers = pe.compute_price_tiers(CATALOG)
    assert tiers["p1"] is PriceTier.PREMIUM
    assert tiers["p3"] is PriceTier.BUDGET


def test_price_tiers_handle_a_catalog_with_no_prices():
    assert pe.compute_price_tiers([{"product_id": "p1", "price": None}]) == {}


def test_price_tier_of_a_single_product_is_not_invented():
    tiers = pe.compute_price_tiers([product("only", price=500.0)])
    assert tiers["only"] in set(PriceTier)


# --- llm tier -------------------------------------------------------------

def test_llm_adds_occasions(stub_llm):
    assert pe.enrich_products(CATALOG)[0].occasions == ["festive"]


def test_llm_output_is_canonicalized_at_the_boundary(stub_llm):
    # "Diwali" must never reach storage; it canonicalizes to "festive" or the
    # join key silently fragments.
    assert "Diwali" not in pe.enrich_products(CATALOG)[0].occasions


def test_llm_fields_are_lowercased(stub_llm):
    record = pe.enrich_products(CATALOG)[0]
    assert record.materials == ["silk"] and record.style_descriptors == ["handloom"]


def test_llm_sets_audience(stub_llm):
    assert pe.enrich_products(CATALOG)[0].audience is Audience.WOMEN


def test_source_records_that_the_model_contributed(stub_llm):
    assert pe.enrich_products(CATALOG)[0].source == "rule_based+llm"


def test_llm_never_removes_a_rule_based_category(stub_llm):
    # The model may only ADD to the deterministic result.
    assert "Saris" in pe.enrich_products(CATALOG)[0].categories


# --- degradation ----------------------------------------------------------

def test_a_failing_batch_keeps_the_rule_based_floor(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(pe, "_enrich_batch_llm",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    records = pe.enrich_products(CATALOG)
    assert len(records) == 3 and records[0].source == "rule_based"
    assert "Saris" in records[0].categories


def test_a_vacuous_response_is_treated_as_failure(monkeypatch):
    # Schema-valid emptiness is the documented Groq failure mode; it must not
    # be read as "this product has no occasions".
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(pe, "_enrich_batch_llm",
                        lambda *a, **k: ProductEnrichmentBatchLLM(products={}))
    assert pe.enrich_products(CATALOG)[0].source == "rule_based"


def test_an_invented_index_is_ignored(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(pe, "_enrich_batch_llm", lambda *a, **k: batch_response(
        {99: {"occasions": ["festive"]}}
    ))
    assert all(not r.occasions for r in pe.enrich_products(CATALOG))


def test_batching_covers_the_whole_catalog(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    seen = []

    def fake(batch, *a, **k):
        seen.append(len(batch))
        return batch_response({0: {"occasions": ["festive"]}})

    monkeypatch.setattr(pe, "_enrich_batch_llm", fake)
    pe.enrich_products([product(f"p{i}") for i in range(25)], batch_size=10)
    assert seen == [10, 10, 5]


# --- strict schema --------------------------------------------------------

def test_enrichment_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ProductEnrichmentLLM(occasions=[], invented_field="x")


def test_enrichment_schema_rejects_an_invalid_audience():
    with pytest.raises(ValidationError):
        ProductEnrichmentLLM(audience="grandparents")


def test_unmappable_occasions_are_dropped():
    assert ProductEnrichmentLLM(occasions=["interstellar"]).occasions == []


def test_empty_batch_is_vacuous():
    assert ProductEnrichmentBatchLLM(products={}).is_vacuous is True


def test_has_occasions_flags_a_product_invisible_to_signals():
    from app.enrichment.models import EnrichedProduct
    assert EnrichedProduct(product_id="p").has_occasions is False
    assert EnrichedProduct(product_id="p", occasions=["festive"]).has_occasions is True


# --- persistence ----------------------------------------------------------

def test_save_then_load_roundtrips(conn, stub_llm):
    records = pe.enrich_products(CATALOG)
    pe.save_enriched(conn, FINGERPRINT, records)
    loaded = pe.load_enriched(conn, FINGERPRINT)
    assert len(loaded) == 3
    assert loaded[0].occasions == ["festive"]
    assert loaded[0].audience is Audience.WOMEN


def test_saving_twice_updates_in_place(conn, no_llm):
    records = pe.enrich_products(CATALOG)
    pe.save_enriched(conn, FINGERPRINT, records)
    pe.save_enriched(conn, FINGERPRINT, records)
    assert len(pe.load_enriched(conn, FINGERPRINT)) == 3


def test_enrichment_is_scoped_to_a_catalog(conn, no_llm):
    pe.save_enriched(conn, FINGERPRINT, pe.enrich_products(CATALOG))
    assert pe.load_enriched(conn, "different-catalog") == []


def test_get_or_enrich_builds_then_reuses(conn, no_llm, monkeypatch):
    _, built = pe.get_or_enrich(conn, CATALOG, FINGERPRINT, use_llm=False)
    assert built is True
    monkeypatch.setattr(pe, "enrich_products",
                        lambda *a, **k: pytest.fail("must not re-enrich"))
    _, built_again = pe.get_or_enrich(conn, CATALOG, FINGERPRINT, use_llm=False)
    assert built_again is False


def test_a_new_catalog_fingerprint_triggers_fresh_enrichment(conn, no_llm):
    pe.get_or_enrich(conn, CATALOG, FINGERPRINT, use_llm=False)
    _, built = pe.get_or_enrich(conn, CATALOG, "another-fp", use_llm=False)
    assert built is True


# --- the join this all exists for ----------------------------------------

def test_a_festival_signal_reaches_products_through_occasions(conn, stub_llm):
    """The end-to-end point of the rework.

    Under the old design "Diwali" tagged to [] and was discarded before it
    could reach anything. Occasion overlap is what makes the causal relation
    (an event drives demand for a product) expressible as a join.
    """
    records = pe.enrich_products(CATALOG)
    diwali_occasions = {"festive", "gifting"}
    matched = [r for r in records if set(r.occasions) & diwali_occasions]
    assert matched, "a festival signal must be able to reach products"
