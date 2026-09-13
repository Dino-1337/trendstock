"""Enrich catalog products with categories, occasions, materials and audience.

Replaces the old product-tagging pass. The substantive change is `occasions`:
categories alone could only ever express "these are the same kind of thing",
which is why a festival could never reach a product. Occasion expresses "these
are used for the same thing", which is the relation that actually drives
demand.

Batched, cached, and degrades to the rule-based floor whenever the model is
unavailable or returns nothing useful - the fallback philosophy from
app/tagging/tagger.py, which exists because Groq once returned a well-formed
empty result for "nike air max".
"""

import json
from datetime import datetime, timezone

from app.enrichment.models import (
    EnrichedProduct,
    PriceTier,
    ProductEnrichmentBatchLLM,
)
from app.enrichment.occasions import prompt_block
from app.llm import client as llm
from app.logging_setup import get_logger
from app.tagging.rule_based import tag_text
from app.tagging.vocabulary import get_vocabulary

log = get_logger("enrichment")

# Products per model call. Small enough that one failure does not cost the
# whole catalog, large enough to stay well inside the free-tier request budget.
BATCH_SIZE = 10

# Price tier cut points, as quantiles of THIS catalog rather than absolute
# rupee values - a "premium" saree store and a "budget" kurti store have
# completely different ranges, and a fixed threshold would mislabel both.
BUDGET_QUANTILE = 0.33
PREMIUM_QUANTILE = 0.67


def _product_text(product):
    """Everything a tagger or model could reasonably read about a product."""
    parts = [
        product.get("title") or "",
        product.get("product_type") or "",
        product.get("vendor") or "",
        " ".join(product.get("tags") or []),
    ]
    return " ".join(p for p in parts if p).strip()


def compute_price_tiers(products):
    """Assign budget/mid/premium by within-catalog quantile.

    Returns {product_id: PriceTier}. A catalog with no usable prices gets an
    empty map rather than an invented tier.
    """
    priced = [(p.get("product_id"), float(p["price"]))
              for p in products if p.get("price") is not None]
    if not priced:
        return {}

    values = sorted(v for _, v in priced)

    def quantile(q):
        if len(values) == 1:
            return values[0]
        index = min(int(q * (len(values) - 1)), len(values) - 1)
        return values[index]

    low, high = quantile(BUDGET_QUANTILE), quantile(PREMIUM_QUANTILE)

    tiers = {}
    for product_id, price in priced:
        if price <= low:
            tiers[product_id] = PriceTier.BUDGET
        elif price >= high:
            tiers[product_id] = PriceTier.PREMIUM
        else:
            tiers[product_id] = PriceTier.MID
    return tiers


def _build_prompt(products, store_context=None):
    numbered = "\n".join(
        f"{i}: {_product_text(p)}" for i, p in enumerate(products)
    )
    context = f"\nSTORE CONTEXT:\n{store_context}\n" if store_context else ""

    return (
        "You are enriching an e-commerce catalog so seasonal demand signals "
        "can be matched to products. For each numbered product, decide what "
        "OCCASIONS it is bought for, what it is made of, and who it is for.\n"
        f"{context}\n"
        "OCCASIONS - choose only from this fixed list, using the exact slug:\n"
        f"{prompt_block()}\n\n"
        "Pick every occasion that genuinely applies (most products have 1-3). "
        "Be accurate rather than generous: an occasion you add wrongly will "
        "surface irrelevant alerts to the seller.\n\n"
        "AUDIENCE - one of: women, men, unisex, kids.\n"
        "MATERIALS - fabrics or materials named or strongly implied "
        "(silk, cotton, leather, ...). Empty list if unclear.\n"
        "STYLE - short descriptive words (embroidered, printed, handloom, ...).\n\n"
        f"PRODUCTS:\n{numbered}\n\n"
        "Respond with ONLY a single JSON object (no prose, no markdown fences) "
        'of the form:\n'
        '{"products": {"0": {"occasions": ["festive"], "materials": ["silk"], '
        '"audience": "women", "style_descriptors": ["handloom"]}}}\n'
        "Every product number above must appear as a key."
    )


def _enrich_batch_llm(products, store_context=None, models=None):
    """One model call for a batch. Raises on failure; callers decide fallback."""
    messages = [{"role": "user", "content": _build_prompt(products, store_context)}]
    return llm.structured(
        messages,
        ProductEnrichmentBatchLLM,
        models=models or llm.MODELS,
        max_tokens=1600,
    )


def enrich_products(products, store_context=None, use_llm=True, models=None,
                    batch_size=BATCH_SIZE, vocabulary=None):
    """Enrich a catalog, returning a list of EnrichedProduct.

    Categories always come from the deterministic tagger. Model output only
    ADDS occasions/materials/audience/style on top - it can never remove or
    replace a rule-based category, matching how tagger.py treats Groq output.
    """
    products = products or []
    if not products:
        return []

    vocabulary = vocabulary or get_vocabulary()
    tiers = compute_price_tiers(products)

    # Deterministic floor first, so a total LLM outage still yields categories.
    enriched = {}
    for product in products:
        product_id = product.get("product_id")
        enriched[product_id] = EnrichedProduct(
            product_id=product_id,
            title=product.get("title"),
            categories=tag_text(_product_text(product), vocabulary).tags,
            price_tier=tiers.get(product_id),
            source="rule_based",
        )

    if not use_llm or not llm.is_available():
        return list(enriched.values())

    for start in range(0, len(products), batch_size):
        batch = products[start:start + batch_size]
        try:
            result = _enrich_batch_llm(batch, store_context, models)
        except Exception as exc:
            # One bad batch must not cost the rest of the catalog.
            log.warning("enrichment batch %d failed, keeping rule-based: %s", start, exc)
            continue

        if result.is_vacuous:
            log.warning("enrichment batch %d returned nothing usable", start)
            continue

        for index_str, item in result.products.items():
            try:
                product = batch[int(index_str)]
            except (ValueError, IndexError):
                continue  # model invented an index
            record = enriched.get(product.get("product_id"))
            if record is None:
                continue
            record.occasions = item.occasions
            record.materials = item.materials
            record.audience = item.audience
            record.style_descriptors = item.style_descriptors
            record.source = "rule_based+llm"

    return list(enriched.values())


# --- persistence ----------------------------------------------------------

def save_enriched(conn, fingerprint, records, now=None):
    """Upsert enrichment rows for one catalog."""
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    for record in records:
        conn.execute(
            """
            INSERT INTO enriched_products (
                catalog_fingerprint, product_id, title, categories, occasions,
                materials, audience, style_descriptors, price_tier, source,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (catalog_fingerprint, product_id) DO UPDATE SET
                title             = excluded.title,
                categories        = excluded.categories,
                occasions         = excluded.occasions,
                materials         = excluded.materials,
                audience          = excluded.audience,
                style_descriptors = excluded.style_descriptors,
                price_tier        = excluded.price_tier,
                source            = excluded.source,
                updated_at        = excluded.updated_at
            """,
            (
                fingerprint, record.product_id, record.title,
                json.dumps(record.categories, ensure_ascii=False),
                json.dumps(record.occasions, ensure_ascii=False),
                json.dumps(record.materials, ensure_ascii=False),
                record.audience.value if record.audience else None,
                json.dumps(record.style_descriptors, ensure_ascii=False),
                record.price_tier.value if record.price_tier else None,
                record.source, stamp, stamp,
            ),
        )
    return len(records)


def _row_to_record(row):
    return EnrichedProduct(
        product_id=row["product_id"],
        title=row["title"],
        categories=json.loads(row["categories"] or "[]"),
        occasions=json.loads(row["occasions"] or "[]"),
        materials=json.loads(row["materials"] or "[]"),
        audience=row["audience"],
        style_descriptors=json.loads(row["style_descriptors"] or "[]"),
        price_tier=row["price_tier"],
        source=row["source"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def load_enriched(conn, fingerprint):
    rows = conn.execute(
        "SELECT * FROM enriched_products WHERE catalog_fingerprint = ? ORDER BY id",
        (fingerprint,),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def get_or_enrich(conn, products, fingerprint, store_context=None, use_llm=True,
                  models=None, now=None):
    """Load enrichment for this catalog, or produce and store it.

    Cached on the catalog fingerprint, so re-running the pipeline costs
    nothing while the catalog is unchanged and re-enriches automatically when
    the seller uploads a different one.
    """
    existing = load_enriched(conn, fingerprint)
    if existing:
        return existing, False

    records = enrich_products(
        products, store_context=store_context, use_llm=use_llm, models=models
    )
    save_enriched(conn, fingerprint, records, now=now)
    return records, True
