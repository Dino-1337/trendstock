"""The relevance gate - the main fix for the actual user complaint: the
trending feed surfaces things like a cricketer's name or a state government
reshuffle, which are useless to a niche seller. Raw trend strings and product
titles live in different vocabularies, so string matching alone can never
tell "ईशान किशन" from "chunky claw clips" - but the controlled-vocabulary
tagger can, because one resolves to zero commerce tags and the other doesn't.

This is a FILTER before it is a matcher: a trend needs no translating or
scoring against the catalog to be recognised as noise - zero commerce tags is
enough to drop it, with the reason recorded so the drop is auditable rather
than a silent, unexplained shrink of the trend list.
"""

NO_TAGS_REASON = "No commerce-relevant tags found in the trend name or headlines."


def apply_relevance_gate(trends, tag_results):
    """trends: list of trend dicts, each with an 'id' key.
    tag_results: {trend_id: TagResult}, e.g. from trend_tagger.tag_trends().

    Returns (kept, dropped):
    - kept: the same trend dicts, each with 'category_tags' (list[str]) and
      'tag_source' ("rule_based" | "llm_groq") attached.
    - dropped: [{"trend": name, "reason": str}] for every trend cut, in the
      original order, so the count and the reasons are both inspectable.
    """
    kept = []
    dropped = []
    for trend in trends:
        result = tag_results.get(trend.get("id"))
        tags = result.tags if result else []
        if tags:
            enriched = dict(trend)
            enriched["category_tags"] = tags
            enriched["tag_source"] = result.source
            kept.append(enriched)
        else:
            dropped.append({"trend": trend.get("trend"), "reason": NO_TAGS_REASON})
    return kept, dropped
