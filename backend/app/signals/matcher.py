"""Match interpreted signals to enriched products.

Deliberately deterministic and cheap. All the semantic work already happened
once per signal (interpretation) and once per product (enrichment); this layer
just intersects the results. That is what keeps the expensive step at "a
handful of model calls a day" instead of one per signal x product pair.

Scoring, and why each weight is what it is:

- OCCASION overlap is the primary signal and a hard requirement. It is the
  relation that actually drives demand ("this event makes people buy this kind
  of thing") and the whole reason the rework happened. No overlap, no match -
  otherwise a festival would "match" every product in the catalog weakly and
  the ranking would be noise.
- CATEGORY overlap is a strong bonus, not a requirement. When a signal names a
  category outright ("saree demand rising"), products in it should outrank
  other festive items. But requiring it would reintroduce the old failure:
  "Diwali" names no category at all.
- AUDIENCE conflict is a penalty rather than a veto. A menswear signal against
  a womenswear product is usually wrong but occasionally right (gifting), so
  it is demoted, not hidden.
"""

OCCASION_BASE = 0.5          # any occasion overlap at all
OCCASION_EXTRA = 0.1         # per additional overlapping occasion
OCCASION_EXTRA_CAP = 0.2

CATEGORY_BONUS = 0.3         # the signal named this product's category
AUDIENCE_BONUS = 0.1
AUDIENCE_PENALTY = -0.25

# Below this a "match" is too weak to show; it would be an audience-penalised
# single-occasion overlap, which in practice reads as a false positive.
MIN_SCORE = 0.4


def score(signal, product):
    """Score one (signal, product) pair in 0..1. Returns (score, reasons)."""
    occasion_overlap = [o for o in product.occasions if o in set(signal.affected_occasions)]
    if not occasion_overlap:
        return 0.0, []

    reasons = [f"occasion: {', '.join(occasion_overlap)}"]
    total = OCCASION_BASE + min(
        OCCASION_EXTRA * (len(occasion_overlap) - 1), OCCASION_EXTRA_CAP
    )

    category_overlap = [c for c in product.categories if c in set(signal.affected_categories)]
    if category_overlap:
        total += CATEGORY_BONUS
        reasons.append(f"category: {', '.join(category_overlap)}")

    product_audience = product.audience.value if product.audience else None
    if signal.audience and product_audience:
        if signal.audience == product_audience:
            total += AUDIENCE_BONUS
            reasons.append(f"audience: {product_audience}")
        elif "unisex" not in (signal.audience, product_audience):
            total += AUDIENCE_PENALTY
            reasons.append(f"audience mismatch: {product_audience} vs {signal.audience}")

    return min(round(total, 3), 1.0), reasons


def match_signal(signal, products, min_score=MIN_SCORE, limit=None):
    """Products affected by one signal, best first."""
    if not signal.can_match:
        return []

    matches = []
    for product in products:
        value, reasons = score(signal, product)
        if value >= min_score:
            matches.append({
                "product_id": product.product_id,
                "title": product.title,
                "score": value,
                "reasons": reasons,
            })

    matches.sort(key=lambda m: (-m["score"], m["title"] or ""))
    return matches[:limit] if limit else matches


def match_all(signals, products, today=None, min_score=MIN_SCORE, in_window_only=False):
    """Match every signal, returning them annotated with their matches.

    Sorted by urgency (soonest dated event first, undated trends after), which
    is how the dashboard wants to read them - the seller acts on what is
    closest, not on what scores highest.
    """
    out = []
    for signal in signals:
        if in_window_only and not signal.is_in_lead_window(today):
            continue
        matches = match_signal(signal, products, min_score=min_score)
        out.append({
            "signal": signal,
            "matches": matches,
            "days_until": signal.days_until(today),
            "in_window": signal.is_in_lead_window(today),
        })

    def sort_key(entry):
        days = entry["days_until"]
        # Undated trends sort after dated events rather than being treated as
        # infinitely far away or infinitely urgent.
        return (days is None, days if days is not None else 0)

    out.sort(key=sort_key)
    return out


def products_at_risk(matched, product_lookup, max_days_cover=14):
    """Flatten matches into stockout warnings.

    The actual deliverable: not "this trend is happening" but "this trend is
    happening AND you are about to run out". A matched product with plenty of
    cover needs no action, so it is not a warning.
    """
    seen = {}
    for entry in matched:
        signal = entry["signal"]
        for match in entry["matches"]:
            product = product_lookup.get(match["product_id"])
            if product is None:
                continue
            cover = product.get("days_stock_remaining")
            if cover is None or cover > max_days_cover:
                continue

            existing = seen.get(match["product_id"])
            # Keep the most urgent signal per product; listing the same saree
            # once per festival would bury the catalog in duplicates.
            if existing and (existing["days_until"] or 999) <= (entry["days_until"] or 999):
                continue

            seen[match["product_id"]] = {
                "product_id": match["product_id"],
                "title": match["title"],
                "signal_name": signal.name,
                "signal_type": signal.signal_type.value,
                "event_date": signal.event_date.isoformat() if signal.event_date else None,
                "days_until": entry["days_until"],
                "days_stock_remaining": cover,
                "current_stock": product.get("current_stock"),
                "score": match["score"],
                "reasons": match["reasons"],
                "demand_lift": signal.demand_lift.value if signal.demand_lift else None,
            }

    return sorted(seen.values(), key=lambda r: r["days_stock_remaining"])
