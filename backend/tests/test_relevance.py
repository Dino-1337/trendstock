"""Relevance gate (app/tagging/relevance.py): the main fix for the user's
complaint - a trend with zero commerce-relevant tags is dropped before it
reaches matching or the API, with the reason recorded for auditability."""

from app.tagging.base import TagResult
from app.tagging.relevance import apply_relevance_gate


def test_trend_with_tags_is_kept_and_enriched():
    trends = [{"id": "t1", "trend": "nike sneakers restock"}]
    tag_results = {"t1": TagResult(tags=["Sneakers"], source="rule_based")}
    kept, dropped = apply_relevance_gate(trends, tag_results)

    assert len(kept) == 1
    assert kept[0]["category_tags"] == ["Sneakers"]
    assert kept[0]["tag_source"] == "rule_based"
    assert dropped == []


def test_trend_with_no_tags_is_dropped_with_reason():
    trends = [{"id": "t1", "trend": "ईशान किशन cricket duleep trophy"}]
    tag_results = {"t1": TagResult(tags=[], source="rule_based")}
    kept, dropped = apply_relevance_gate(trends, tag_results)

    assert kept == []
    assert len(dropped) == 1
    assert dropped[0]["trend"] == "ईशान किशन cricket duleep trophy"
    assert dropped[0]["reason"]


def test_missing_tag_result_is_treated_as_no_tags():
    """A trend id absent from tag_results entirely (should not normally
    happen, but must degrade safely) is dropped, not crash."""
    trends = [{"id": "t1", "trend": "something"}]
    kept, dropped = apply_relevance_gate(trends, {})
    assert kept == []
    assert len(dropped) == 1


def test_mixed_batch_keeps_only_relevant_and_preserves_order():
    trends = [
        {"id": "t1", "trend": "milan vs inter"},
        {"id": "t2", "trend": "nike sneakers"},
        {"id": "t3", "trend": "state election results"},
        {"id": "t4", "trend": "puma slides"},
    ]
    tag_results = {
        "t1": TagResult(tags=[], source="rule_based"),
        "t2": TagResult(tags=["Sneakers"], source="rule_based"),
        "t3": TagResult(tags=[], source="rule_based"),
        "t4": TagResult(tags=["Sandals"], source="llm_groq"),
    }
    kept, dropped = apply_relevance_gate(trends, tag_results)

    assert [t["trend"] for t in kept] == ["nike sneakers", "puma slides"]
    assert [d["trend"] for d in dropped] == ["milan vs inter", "state election results"]


def test_gate_does_not_mutate_the_input_trend_dicts():
    trend = {"id": "t1", "trend": "nike sneakers"}
    trends = [trend]
    tag_results = {"t1": TagResult(tags=["Sneakers"], source="rule_based")}
    apply_relevance_gate(trends, tag_results)
    assert "category_tags" not in trend  # the original dict is untouched; a copy was enriched
