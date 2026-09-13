"""Trend <-> catalog matching, weighted.

This used to be naive any-word matching: "nike sneakers" matched 17 products
including Puma, and "puma slides" matched Puma Sneakers (right brand, wrong
type) and Converse Slides (right type, wrong brand). A brand/type gating
version fixed that; this version replaces gating with real category tags
from the controlled-vocabulary tagger (app/tagging/) plus explicit weighting:

- Category agreement (the tagger's controlled-vocabulary tags overlapping
  between trend and product) is the strong signal and the baseline score.
- Brand agreement is a BONUS on top of category agreement, not a substitute
  for it - a brand match with no category overlap still isn't a match.
- Brand CONFLICT is an explicit penalty, not neutral: a trend naming a
  competitor brand (e.g. "adidas" when the seller sells Nike) is *weaker*
  evidence than a trend naming no brand at all, because it's positively
  describing a different product. The penalty is sized to fully cancel the
  category-only baseline, which is what keeps the original bug fixed under
  this scheme: "nike sneakers" still can't match Puma Sneakers (category
  agrees, brand conflicts, nets to 0) and "puma slides" still can't match
  Puma Sneakers (no category agreement at all - Sandals vs Sneakers -
  excluded outright regardless of brand) or Converse Slides (category
  agrees, brand conflicts, nets to 0).
- No category overlap at all -> no match, full stop. A trend can share a
  brand word with a product and still not match it if they're not even in
  the same commerce category.

Known limitation: this sample catalog's tags come from product_type/vendor/
title/tags alone (see app/tagging/product_tagger.py), so category tagging is
only as fine-grained as "Sneakers"/"Sandals"/"T-Shirts" - a trend naming a
style, not a category or brand, still matches every product in that category
equally, because there is nothing in this catalog's data for a style word to
bind to. That's an honest reflection of what this data supports, not a bug.
"""

import re

from app.tagging.trend_tagger import trend_text_blob

_WORD_RE = re.compile(r"[a-z0-9]+")

CATEGORY_AGREEMENT_SCORE = 0.6
BRAND_AGREEMENT_BONUS = 0.3
BRAND_CONFLICT_PENALTY = 0.6


def tokenize(text):
    return set(_WORD_RE.findall((text or "").lower()))


def build_brand_vocab(products):
    """The catalog's own vendor vocabulary - no hardcoded brand list, so a
    different uploaded CSV brings its own brands with zero code changes."""
    return {p["vendor"].lower() for p in products if p.get("vendor")}


def score_trend_product(trend_tags, trend_text, product, known_vendors):
    """trend_tags: set of controlled-vocabulary category names already
    resolved for this trend (see app/tagging/relevance.py's 'category_tags'
    field). trend_text: raw trend name + headlines, scanned only for brand
    words. product: needs 'vendor' and 'category_tags' (controlled-vocabulary
    category names from app/tagging/product_tagger.py - NOT the raw CSV
    'tags' field, which is a different, pre-existing thing on product dicts).
    """
    product_tags = set(product.get("category_tags") or [])
    category_overlap = trend_tags & product_tags
    if not category_overlap:
        return 0.0

    trend_words = tokenize(trend_text)
    vendor = (product.get("vendor") or "").lower()
    brand_words_in_trend = trend_words & known_vendors
    brand_hit = bool(vendor) and vendor in brand_words_in_trend
    brand_conflict = bool(brand_words_in_trend) and not brand_hit

    score = CATEGORY_AGREEMENT_SCORE
    if brand_conflict:
        score -= BRAND_CONFLICT_PENALTY
    elif brand_hit:
        score += BRAND_AGREEMENT_BONUS

    return round(max(0.0, min(1.0, score)), 2)


def match_trends_to_catalog(trends, products, known_vendors=None):
    """trends: list of dicts with 'trend', 'classification', and
    'category_tags' (a list of controlled-vocabulary category names - see
    relevance.py; trends that failed the relevance gate should already be
    excluded by the caller). products: list of product dicts, each already
    carrying 'category_tags' (attached by app/tagging/product_tagger.py
    before this is called).

    Returns (products, gaps, match_counts). Mutates each product in place,
    attaching a sorted (best-first) 'matched_trends' list.
    """
    known_vendors = known_vendors if known_vendors is not None else build_brand_vocab(products)

    for product in products:
        product["matched_trends"] = []

    match_counts = {}
    for trend in trends:
        trend_name = trend.get("trend")
        trend_tags = set(trend.get("category_tags") or [])
        trend_text = trend_text_blob(trend)
        match_counts[trend_name] = 0
        for product in products:
            score = score_trend_product(trend_tags, trend_text, product, known_vendors)
            if score > 0:
                product["matched_trends"].append({
                    "trend": trend_name,
                    "classification": trend.get("classification", "new"),
                    "score": score,
                })
                match_counts[trend_name] += 1

    for product in products:
        product["matched_trends"].sort(key=lambda m: m["score"], reverse=True)

    gaps = [
        {
            "trend": trend.get("trend"),
            "classification": trend.get("classification", "new"),
            "reason": "No catalog product matches this trend.",
        }
        for trend in trends
        if match_counts.get(trend.get("trend"), 0) == 0
    ]

    return products, gaps, match_counts
