"""Deterministic rule-based tagger (app/tagging/rule_based.py). No network,
no key, always available - this is what runs today and the permanent
fallback whenever Groq isn't."""

from app.tagging.rule_based import tag_text
from app.tagging.vocabulary import get_vocabulary


def test_tags_product_style_text():
    v = get_vocabulary()
    result = tag_text("Title: Nike Sneakers 0. Type: sneakers. Vendor: Nike. Tags: nike, sneakers.", v)
    assert result.tags == ["Sneakers"]
    assert result.source == "rule_based"


def test_tags_trend_style_text_with_headline():
    v = get_vocabulary()
    result = tag_text("puma slides. summer slide sandals restocking across stores.", v)
    assert result.tags == ["Sandals"]
    assert result.source == "rule_based"


def test_untaggable_text_returns_empty_not_an_error():
    v = get_vocabulary()
    result = tag_text("ईशान किशन cricket duleep trophy north zone team", v)
    assert result.tags == []
    assert result.source == "rule_based"


def test_empty_text_returns_empty():
    v = get_vocabulary()
    result = tag_text("", v)
    assert result.tags == []
    result = tag_text(None, v)
    assert result.tags == []


def test_detail_records_which_vocabulary_term_matched():
    v = get_vocabulary()
    result = tag_text("puma slides", v)
    assert any(d["tag"] == "Sandals" and d["kind"] == "attribute_value" for d in result.detail)
