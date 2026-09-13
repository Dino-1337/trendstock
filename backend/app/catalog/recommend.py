"""Map (trend classification x stock status) to a concrete action.

Every recommendation carries a plain-English reason that cites the actual
numbers behind it (PRD 8: "every recommendation is explainable"). Nothing here
is a black box - the reason string always names the trend (if any), its
classification, and the days of stock remaining that drove the decision.
"""

# Highest-priority classification first: if a product matches several trends,
# the most demand-relevant one drives the recommendation.
_CLASSIFICATION_PRIORITY = ["spiking", "rising", "falling", "steady", "new"]


def _driving_trend(matched_trends):
    if not matched_trends:
        return None

    def priority(m):
        classification = m.get("classification", "new")
        try:
            return _CLASSIFICATION_PRIORITY.index(classification)
        except ValueError:
            return len(_CLASSIFICATION_PRIORITY)

    return sorted(matched_trends, key=priority)[0]


def recommend_action(matched_trends, stock_status, days_stock_remaining):
    """matched_trends: a product's matched_trends list (may be empty).
    stock_status: 'critical' | 'low' | 'ok'.
    days_stock_remaining: number, used verbatim in the reason text.

    Returns {"action": ..., "reason": ...}.
    """
    driving = _driving_trend(matched_trends)
    classification = driving["classification"] if driving else None
    trend_name = driving["trend"] if driving else None
    days = days_stock_remaining

    if classification == "spiking":
        if stock_status in ("critical", "low"):
            return {
                "action": "reduce_reorder_risk",
                "reason": (
                    f"'{trend_name}' is spiking but only {days} days of stock remain "
                    "- reorder now before demand outpaces supply."
                ),
            }
        return {
            "action": "promote",
            "reason": (
                f"'{trend_name}' is spiking and you have {days} days of stock "
                "- promote now while visibility is high."
            ),
        }

    if classification == "rising":
        if stock_status == "critical":
            return {
                "action": "reduce_reorder_risk",
                "reason": (
                    f"'{trend_name}' is rising but stock is critical ({days} days) "
                    "- reorder now."
                ),
            }
        if stock_status == "low":
            return {
                "action": "increase_stock",
                "reason": (
                    f"'{trend_name}' is rising and stock is running low ({days} days) "
                    "- increase stock, elevated demand is expected."
                ),
            }
        return {
            "action": "promote",
            "reason": (
                f"'{trend_name}' is rising and you have {days} days of stock "
                "- good time to promote."
            ),
        }

    if classification == "falling":
        return {
            "action": "discount",
            "reason": (
                f"'{trend_name}' is fading - consider discounting to move the "
                f"remaining {days} days of stock before demand drops further."
            ),
        }

    # classification is None (no matched trend), "new" (no history yet), or
    # "steady" (no notable movement) - none of these justify a demand-driven
    # action on their own, so stock level alone decides.
    if stock_status in ("critical", "low"):
        if trend_name:
            context = f"trend '{trend_name}' has no clear momentum yet"
        else:
            context = "not matched to a tracked trend"
        return {
            "action": "reduce_reorder_risk",
            "reason": f"Only {days} days of stock remaining ({context}) - restock to avoid a stockout.",
        }

    if trend_name:
        return {
            "action": "none",
            "reason": (
                f"'{trend_name}' has no clear momentum yet and stock is healthy "
                f"({days} days) - no action needed."
            ),
        }
    return {
        "action": "none",
        "reason": f"Not matched to a tracked trend, and stock is healthy ({days} days) - no action needed.",
    }
