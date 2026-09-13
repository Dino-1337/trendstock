"""Trend tagger (app/tagging/trend_tagger.py): tags from the trend name PLUS
its news headlines, since a bare two-word trend name is often untaggable on
its own but the headline explaining the spike usually says more."""

from app.tagging.trend_tagger import tag_trends, trend_text_blob
from app.tagging.vocabulary import get_vocabulary


def test_trend_text_blob_includes_name_and_headlines():
    trend = {
        "trend": "the mummy 4",
        "why": [
            {"headline": "The Mummy Cast Adds Numan Acar", "source": "Deadline"},
            {"headline": "Brendan Fraser sequel news", "source": "MovieWeb"},
        ],
    }
    blob = trend_text_blob(trend)
    assert "the mummy 4" in blob
    assert "Numan Acar" in blob
    assert "Brendan Fraser" in blob


def test_trend_text_blob_handles_missing_why():
    trend = {"trend": "nike sneakers"}
    assert trend_text_blob(trend) == "nike sneakers."


def test_headline_can_supply_the_only_tag_signal():
    """A bare trend name with nothing taggable, but a headline that mentions
    a real product category, should still tag correctly - this is the whole
    point of including headlines."""
    trend = {
        "trend": "XY-42",
        "why": [{"headline": "New sneaker drop XY-42 sells out in minutes", "source": "Sneaker News"}],
    }
    vocabulary = get_vocabulary()
    results = tag_trends([{"id": "t1", **trend}], vocabulary)
    assert results["t1"].tags == ["Sneakers"]


def test_tag_trends_drops_nothing_relevant_for_untaggable_trend():
    trend = {"id": "t1", "trend": "ईशान किशन", "why": [
        {"headline": "cricket duleep trophy north zone team", "source": "AajTak"},
    ]}
    vocabulary = get_vocabulary()
    results = tag_trends([trend], vocabulary)
    assert results["t1"].tags == []
