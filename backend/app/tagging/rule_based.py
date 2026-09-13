"""Deterministic tagger: normalize text, match it against the controlled
vocabulary (category names + curated attribute-value synonyms), no network,
no key required. This is the tagger that runs today, and the permanent
fallback for whenever the LLM path is unavailable or untrustworthy."""

from app.tagging.base import TagResult
from app.tagging.vocabulary import get_vocabulary


def tag_text(text, vocabulary=None):
    vocabulary = vocabulary or get_vocabulary()
    hits = vocabulary.match(text or "")
    tags = sorted({tag for tag, _label, _kind in hits})
    detail = [{"tag": tag, "label": label, "kind": kind} for tag, label, kind in hits]
    return TagResult(tags=tags, source="rule_based", detail=detail)
