"""Store-profile tests. The LLM half is always stubbed; the computed half is
exercised for real, because it is meant to work with no key at all.
"""

import pytest
from pydantic import ValidationError

from app.llm import client as llm
from app.profile import builder
from app.profile.models import (
    InferenceSource,
    PricePositioning,
    StoreProfile,
    StoreProfileLLM,
)
from app.storage import db


def product(pid="p1", title="Nike Air Max", ptype="sneakers", price=4000.0,
            tags=("nike", "running"), vendor="Nike", variants=3, stock=10,
            category_tags=None):
    data = {
        "product_id": pid, "title": title, "product_type": ptype, "price": price,
        "tags": list(tags), "vendor": vendor, "variants": variants,
        "current_stock": stock,
    }
    if category_tags is not None:
        data["category_tags"] = category_tags
    return data


CATALOG = [
    product("p1", "Nike Air Max", "sneakers", 5000.0),
    product("p2", "Puma Slides", "slides", 2000.0, vendor="Puma"),
    product("p3", "Adidas Tee", "tshirts", 3000.0, vendor="Adidas"),
]

INFERRED = StoreProfileLLM(
    store_type="athleisure footwear",
    target_audience="young urban shoppers",
    price_positioning=PricePositioning.MID_MARKET,
    style_descriptors=["sporty", "streetwear"],
    summary="A focused athleisure catalog.",
)


@pytest.fixture
def conn(tmp_path):
    connection = db.init_db(db.connect(tmp_path / "t.db"))
    yield connection
    connection.close()


# --- fingerprint ----------------------------------------------------------

def test_same_catalog_gives_the_same_fingerprint():
    assert builder.catalog_fingerprint(CATALOG) == builder.catalog_fingerprint(CATALOG)


def test_row_order_does_not_change_the_fingerprint():
    assert builder.catalog_fingerprint(CATALOG) == builder.catalog_fingerprint(CATALOG[::-1])


def test_changing_a_product_changes_the_fingerprint():
    changed = [product("p1", "Nike Air Max 90"), *CATALOG[1:]]
    assert builder.catalog_fingerprint(changed) != builder.catalog_fingerprint(CATALOG)


def test_restocking_does_not_change_the_fingerprint():
    # The profile describes what is sold, not how much is in stock; a restock
    # must not trigger a rebuild.
    restocked = [{**p, "current_stock": p["current_stock"] + 50} for p in CATALOG]
    assert builder.catalog_fingerprint(restocked) == builder.catalog_fingerprint(CATALOG)


def test_empty_catalog_has_a_stable_fingerprint():
    assert builder.catalog_fingerprint([]) == builder.catalog_fingerprint([])


# --- computed facts -------------------------------------------------------

def test_counts_products_and_variants():
    facts = builder.compute_facts(CATALOG)
    assert (facts.product_count, facts.variant_count) == (3, 9)


def test_computes_price_band():
    facts = builder.compute_facts(CATALOG)
    assert (facts.price_min, facts.price_median, facts.price_max) == (2000.0, 3000.0, 5000.0)


def test_collects_distinct_types_and_vendors():
    facts = builder.compute_facts(CATALOG)
    assert facts.product_types == ["slides", "sneakers", "tshirts"]
    assert facts.vendors == ["Adidas", "Nike", "Puma"]


def test_categories_fall_back_to_product_type_when_untagged():
    counts = {c.name: c.count for c in builder.compute_facts(CATALOG).top_categories}
    assert counts == {"sneakers": 1, "slides": 1, "tshirts": 1}


def test_categories_prefer_vocabulary_tags_when_present():
    tagged = [product("p1", category_tags=["Sneakers", "Athletic Shoes"])]
    counts = {c.name: c.count for c in builder.compute_facts(tagged).top_categories}
    assert counts == {"Sneakers": 1, "Athletic Shoes": 1}


def test_categories_are_ranked_by_count():
    catalog = [product(f"p{i}", ptype="sneakers") for i in range(3)] + [product("x", ptype="slides")]
    assert builder.compute_facts(catalog).top_categories[0].name == "sneakers"


def test_empty_catalog_computes_without_error():
    facts = builder.compute_facts([])
    assert facts.is_empty and facts.price_min is None and facts.product_count == 0


def test_missing_vendor_and_type_are_skipped_not_blank():
    facts = builder.compute_facts([product(ptype="", vendor="")])
    assert facts.product_types == [] and facts.vendors == []


# --- build_profile fallback ----------------------------------------------

def test_profile_is_computed_only_when_llm_disabled():
    profile = builder.build_profile(CATALOG, use_llm=False)
    assert profile.inference_source is InferenceSource.COMPUTED
    assert profile.inferred is None


def test_profile_is_computed_only_when_no_key(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: False)
    assert builder.build_profile(CATALOG).inference_source is InferenceSource.COMPUTED


def test_empty_catalog_skips_the_llm_entirely(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(builder, "infer_profile", lambda *a, **k: pytest.fail("no call"))
    assert builder.build_profile([]).inference_source is InferenceSource.COMPUTED


def test_llm_failure_degrades_instead_of_raising(monkeypatch):
    # Same philosophy as tagger.py: a Groq outage must never take the pipeline
    # down, it must just produce a thinner profile.
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(builder, "infer_profile",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    profile = builder.build_profile(CATALOG)
    assert profile.inference_source is InferenceSource.COMPUTED
    assert profile.facts.product_count == 3


def test_successful_inference_is_recorded(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(builder, "infer_profile", lambda *a, **k: INFERRED)
    profile = builder.build_profile(CATALOG)
    assert profile.inference_source is InferenceSource.COMPUTED_AND_LLM
    assert profile.inferred.store_type == "athleisure footwear"


def test_prompt_does_not_ask_the_model_to_restate_numbers():
    prompt = builder._build_prompt(builder.compute_facts(CATALOG), CATALOG)
    assert "Do NOT restate the numbers" in prompt


def test_prompt_caps_the_number_of_sampled_titles():
    big = [product(f"p{i}", title=f"Product {i}") for i in range(200)]
    prompt = builder._build_prompt(builder.compute_facts(big), big)
    assert prompt.count("\n- ") <= builder.SAMPLE_TITLE_LIMIT


# --- strict LLM schema ----------------------------------------------------

def test_inferred_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        StoreProfileLLM(**{**INFERRED.model_dump(), "revenue": "1cr"})


def test_inferred_schema_rejects_invalid_positioning():
    with pytest.raises(ValidationError):
        StoreProfileLLM(**{**INFERRED.model_dump(), "price_positioning": "cheapish"})


def test_inferred_schema_rejects_blank_summary():
    with pytest.raises(ValidationError):
        StoreProfileLLM(**{**INFERRED.model_dump(), "summary": "   "})


def test_style_descriptors_are_cleaned():
    profile = StoreProfileLLM(**{**INFERRED.model_dump(),
                                 "style_descriptors": [" sporty ", "", "  "]})
    assert profile.style_descriptors == ["sporty"]


# --- prompt context -------------------------------------------------------

def test_prompt_context_works_without_inference():
    context = builder.build_profile(CATALOG, use_llm=False).as_prompt_context()
    assert "Products in catalog: 3" in context
    assert "Store type:" not in context


def test_prompt_context_includes_inference_when_present():
    profile = StoreProfile(facts=builder.compute_facts(CATALOG), inferred=INFERRED,
                           inference_source=InferenceSource.COMPUTED_AND_LLM)
    context = profile.as_prompt_context()
    assert "Store type: athleisure footwear" in context
    assert "Price positioning: mid_market" in context


# --- persistence ----------------------------------------------------------

def test_save_then_load_roundtrips_facts(conn):
    saved = builder.build_profile(CATALOG, use_llm=False)
    builder.save_profile(conn, saved)
    loaded = builder.load_profile(conn)
    assert loaded.facts.product_count == 3
    assert loaded.facts.catalog_fingerprint == saved.facts.catalog_fingerprint


def test_save_then_load_roundtrips_inference(conn):
    profile = StoreProfile(facts=builder.compute_facts(CATALOG), inferred=INFERRED,
                           inference_source=InferenceSource.COMPUTED_AND_LLM)
    builder.save_profile(conn, profile)
    loaded = builder.load_profile(conn)
    assert loaded.inferred.price_positioning is PricePositioning.MID_MARKET
    assert loaded.inferred.style_descriptors == ["sporty", "streetwear"]


def test_computed_only_profile_loads_with_no_inference(conn):
    builder.save_profile(conn, builder.build_profile(CATALOG, use_llm=False))
    assert builder.load_profile(conn).inferred is None


def test_resaving_the_same_catalog_updates_in_place(conn):
    profile = builder.build_profile(CATALOG, use_llm=False)
    builder.save_profile(conn, profile)
    builder.save_profile(conn, profile)
    assert conn.execute("SELECT COUNT(*) FROM store_profile").fetchone()[0] == 1


def test_load_returns_none_when_empty(conn):
    assert builder.load_profile(conn) is None


def test_load_by_fingerprint_finds_the_right_profile(conn):
    builder.save_profile(conn, builder.build_profile(CATALOG, use_llm=False))
    fingerprint = builder.catalog_fingerprint(CATALOG)
    assert builder.load_profile(conn, fingerprint).facts.catalog_fingerprint == fingerprint


def test_load_by_unknown_fingerprint_returns_none(conn):
    builder.save_profile(conn, builder.build_profile(CATALOG, use_llm=False))
    assert builder.load_profile(conn, "nope") is None


# --- get_or_build ---------------------------------------------------------

def test_get_or_build_builds_on_first_call(conn):
    _, built = builder.get_or_build(conn, CATALOG, use_llm=False)
    assert built is True


def test_get_or_build_reuses_an_existing_profile(conn, monkeypatch):
    builder.get_or_build(conn, CATALOG, use_llm=False)
    monkeypatch.setattr(builder, "build_profile",
                        lambda *a, **k: pytest.fail("must not rebuild"))
    _, built = builder.get_or_build(conn, CATALOG, use_llm=False)
    assert built is False


def test_get_or_build_rebuilds_when_the_catalog_changes(conn):
    builder.get_or_build(conn, CATALOG, use_llm=False)
    changed = CATALOG + [product("p4", "New Item", "caps", 900.0)]
    profile, built = builder.get_or_build(conn, changed, use_llm=False)
    assert built is True and profile.facts.product_count == 4


def test_matches_catalog_detects_a_changed_catalog():
    profile = builder.build_profile(CATALOG, use_llm=False)
    assert profile.matches_catalog(builder.catalog_fingerprint(CATALOG)) is True
    assert profile.matches_catalog("other") is False
