"""Tags trends from their name PLUS news headlines - the headlines are
already in the raw feed data and are far richer than a two-word trend name.
"The Mummy 4" alone tags to nothing; a headline about the casting news at
least gives a model (or a human) the context that this is a film. This is
also why headlines are included even though they mostly won't move the tag
for this catalog's narrow apparel/footwear vocabulary - the point is using
the richer signal that already exists in the data rather than discarding it.
"""

from app.tagging.tagger import tag_batch
from app.tagging.vocabulary import get_vocabulary

CACHE_NAMESPACE = "trends"


def trend_text_blob(trend):
    headlines = " ".join(w.get("headline", "") for w in (trend.get("why") or []) if w.get("headline"))
    return f"{trend.get('trend', '')}. {headlines}".strip()


def tag_trends(trends, vocabulary=None):
    """trends: list of dicts with at least 'trend' and optionally 'why'
    (list of {"headline", "source"}), and an 'id' to key results by.
    Returns {trend_id: TagResult}."""
    vocabulary = vocabulary or get_vocabulary()
    items = [(t["id"], trend_text_blob(t)) for t in trends]
    return tag_batch(items, CACHE_NAMESPACE, vocabulary)
