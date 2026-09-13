"""Build and persist the store profile.

Two stages, deliberately independent:

1. `compute_facts` - arithmetic over the catalog. Always runs, never fails,
   never needs a key. If the LLM is unavailable the profile is still real and
   still useful as grounding, just thinner.
2. `infer_profile` - one model call that reads the computed facts plus a sample
   of product titles and returns positioning/audience/aesthetic.

The profile is keyed by a fingerprint of the catalog, so uploading a new CSV
naturally invalidates it rather than leaving a seller described by products
they no longer sell.
"""

import hashlib
import json
from datetime import datetime, timezone
from statistics import median

from app.llm import client as llm
from app.logging_setup import get_logger
from app.profile.models import (
    CategoryCount,
    InferenceSource,
    StoreFacts,
    StoreProfile,
    StoreProfileLLM,
)

log = get_logger("profile")

# How many product titles the model sees. Enough to characterise a catalog,
# small enough to stay well inside Groq's per-minute token budget - the same
# constraint that forced max_tokens down in llm_groq.py.
SAMPLE_TITLE_LIMIT = 40
TOP_CATEGORY_LIMIT = 15


def catalog_fingerprint(products):
    """Stable hash of the catalog's identity-bearing fields.

    Sorted so row order in the CSV cannot change the fingerprint, and limited
    to fields that describe *what is sold* - restocking a product should not
    invalidate the store's profile, so stock levels are excluded.
    """
    parts = sorted(
        "|".join([
            str(p.get("product_id") or ""),
            str(p.get("title") or ""),
            str(p.get("product_type") or ""),
            str(p.get("price") or ""),
            ",".join(sorted(p.get("tags") or [])),
        ])
        for p in products
    )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _category_counts(products):
    """Count categories, preferring the controlled-vocabulary tags when the
    catalog has been through the tagger, and falling back to the seller's own
    free-text product_type when it has not."""
    counts = {}
    for product in products:
        names = product.get("category_tags") or []
        if not names:
            product_type = (product.get("product_type") or "").strip()
            names = [product_type] if product_type else []
        for name in names:
            counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [CategoryCount(name=n, count=c) for n, c in ranked[:TOP_CATEGORY_LIMIT]]


def compute_facts(products):
    products = products or []
    prices = [float(p["price"]) for p in products if p.get("price") is not None]

    return StoreFacts(
        product_count=len(products),
        variant_count=sum(int(p.get("variants") or 0) for p in products),
        price_min=min(prices) if prices else None,
        price_median=round(median(prices), 2) if prices else None,
        price_max=max(prices) if prices else None,
        top_categories=_category_counts(products),
        product_types=sorted(
            {(p.get("product_type") or "").strip() for p in products} - {""}
        ),
        vendors=sorted({(p.get("vendor") or "").strip() for p in products} - {""}),
        catalog_fingerprint=catalog_fingerprint(products),
    )


def _build_prompt(facts, products):
    titles = [p.get("title") or "" for p in products][:SAMPLE_TITLE_LIMIT]
    sample = "\n".join(f"- {t}" for t in titles if t)
    categories = ", ".join(f"{c.name} ({c.count})" for c in facts.top_categories) or "none"
    price_line = (
        f"{facts.price_min:g} to {facts.price_max:g}, median {facts.price_median:g}"
        if facts.price_min is not None
        else "unknown"
    )

    return (
        "You are analysing an e-commerce seller's product catalog to write a "
        "short business profile. This profile will be used later to judge "
        "which seasonal events and festivals are relevant to this specific "
        "store, so focus on what the store sells and who buys it.\n\n"
        f"Products: {facts.product_count}\n"
        f"Price range: {price_line}\n"
        f"Categories: {categories}\n"
        f"Product types: {', '.join(facts.product_types) or 'none'}\n\n"
        f"Sample product titles:\n{sample}\n\n"
        "Do NOT restate the numbers above; they are already recorded. Infer "
        "only what the numbers do not say.\n\n"
        "Respond with ONLY a single JSON object (no prose, no markdown fences) "
        "with exactly these keys:\n"
        '{"store_type": "short phrase, e.g. women\'s ethnic wear", '
        '"target_audience": "who buys from this store", '
        '"price_positioning": "one of: budget, mid_market, premium, luxury, mixed", '
        '"style_descriptors": ["aesthetic", "words"], '
        '"summary": "a short paragraph describing this store"}'
    )


def infer_profile(facts, products, models=None):
    """One model call producing the inferred half of the profile."""
    messages = [{"role": "user", "content": _build_prompt(facts, products)}]
    return llm.structured(
        messages,
        StoreProfileLLM,
        models=models or llm.REASONING_MODELS,
        max_tokens=800,
    )


def build_profile(products, use_llm=True, models=None):
    """Compute the profile, adding model inference when it is available.

    An LLM failure degrades to a computed-only profile rather than raising -
    same philosophy as app/tagging/tagger.py, where a Groq outage must never
    take down the pipeline.
    """
    facts = compute_facts(products)

    if not use_llm or facts.is_empty or not llm.is_available():
        return StoreProfile(facts=facts, inference_source=InferenceSource.COMPUTED)

    try:
        inferred = infer_profile(facts, products, models=models)
    except Exception as exc:
        log.warning("profile inference failed, falling back to computed facts: %s", exc)
        return StoreProfile(facts=facts, inference_source=InferenceSource.COMPUTED)

    return StoreProfile(
        facts=facts,
        inferred=inferred,
        inference_source=InferenceSource.COMPUTED_AND_LLM,
    )


# --- persistence ----------------------------------------------------------

def save_profile(conn, profile, now=None):
    """Upsert on the catalog fingerprint.

    Only one profile per catalog is meaningful, so rebuilding the same catalog
    updates in place instead of accumulating near-identical rows.
    """
    now = (now or datetime.now(timezone.utc)).isoformat()
    facts = profile.facts
    inferred = profile.inferred

    conn.execute(
        """
        INSERT INTO store_profile (
            catalog_fingerprint, product_count, variant_count,
            price_min, price_median, price_max,
            top_categories, product_types, vendors,
            store_type, target_audience, price_positioning,
            style_descriptors, summary, inference_source,
            created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (catalog_fingerprint) DO UPDATE SET
            product_count     = excluded.product_count,
            variant_count     = excluded.variant_count,
            price_min         = excluded.price_min,
            price_median      = excluded.price_median,
            price_max         = excluded.price_max,
            top_categories    = excluded.top_categories,
            product_types     = excluded.product_types,
            vendors           = excluded.vendors,
            store_type        = excluded.store_type,
            target_audience   = excluded.target_audience,
            price_positioning = excluded.price_positioning,
            style_descriptors = excluded.style_descriptors,
            summary           = excluded.summary,
            inference_source  = excluded.inference_source,
            updated_at        = excluded.updated_at
        """,
        (
            facts.catalog_fingerprint, facts.product_count, facts.variant_count,
            facts.price_min, facts.price_median, facts.price_max,
            json.dumps([c.model_dump() for c in facts.top_categories], ensure_ascii=False),
            json.dumps(facts.product_types, ensure_ascii=False),
            json.dumps(facts.vendors, ensure_ascii=False),
            inferred.store_type if inferred else None,
            inferred.target_audience if inferred else None,
            inferred.price_positioning.value if inferred else None,
            json.dumps(inferred.style_descriptors, ensure_ascii=False) if inferred else None,
            inferred.summary if inferred else None,
            profile.inference_source.value,
            now, now,
        ),
    )
    return conn.execute(
        "SELECT id FROM store_profile WHERE catalog_fingerprint = ?",
        (facts.catalog_fingerprint,),
    ).fetchone()["id"]


def _row_to_profile(row):
    facts = StoreFacts(
        product_count=row["product_count"],
        variant_count=row["variant_count"] or 0,
        price_min=row["price_min"],
        price_median=row["price_median"],
        price_max=row["price_max"],
        top_categories=[CategoryCount(**c) for c in json.loads(row["top_categories"] or "[]")],
        product_types=json.loads(row["product_types"] or "[]"),
        vendors=json.loads(row["vendors"] or "[]"),
        catalog_fingerprint=row["catalog_fingerprint"],
    )

    inferred = None
    if row["store_type"]:
        inferred = StoreProfileLLM(
            store_type=row["store_type"],
            target_audience=row["target_audience"],
            price_positioning=row["price_positioning"],
            style_descriptors=json.loads(row["style_descriptors"] or "[]"),
            summary=row["summary"],
        )

    return StoreProfile(
        id=row["id"],
        facts=facts,
        inferred=inferred,
        inference_source=row["inference_source"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def load_profile(conn, fingerprint=None):
    """Load a profile by fingerprint, or the most recent one if not given."""
    if fingerprint:
        row = conn.execute(
            "SELECT * FROM store_profile WHERE catalog_fingerprint = ?", (fingerprint,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM store_profile ORDER BY updated_at DESC, id DESC LIMIT 1"
        ).fetchone()
    return _row_to_profile(row) if row else None


def get_or_build(conn, products, use_llm=True, models=None, now=None):
    """Return the stored profile if it still matches the catalog, else rebuild.

    This is the onboarding entry point: cheap on every run after the first,
    and self-invalidating when the seller uploads a different CSV.
    """
    fingerprint = catalog_fingerprint(products or [])
    existing = load_profile(conn, fingerprint)
    if existing is not None:
        return existing, False

    profile = build_profile(products, use_llm=use_llm, models=models)
    profile.id = save_profile(conn, profile, now=now)
    return profile, True
