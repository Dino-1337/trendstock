"""Section G: (classification x stock_status) -> action, with an explainable reason."""

import pytest

from app.catalog.recommend import recommend_action



# "Sneakers" is a real controlled-vocabulary category tag this system
# actually produces (see app/tagging/vocabulary.py) - not an invented
# one-off test phrase.
def matched(classification, trend="Sneakers", score=0.9):
    return [{"trend": trend, "classification": classification, "score": score}]


@pytest.mark.parametrize("stock_status,expected_action", [
    ("critical", "reduce_reorder_risk"),
    ("low", "reduce_reorder_risk"),
    ("ok", "promote"),
])
def test_spiking_matrix(stock_status, expected_action):
    result = recommend_action(matched("spiking"), stock_status, 5)
    assert result["action"] == expected_action
    assert "Sneakers" in result["reason"]
    assert "5" in result["reason"]


@pytest.mark.parametrize("stock_status,expected_action", [
    ("critical", "reduce_reorder_risk"),
    ("low", "increase_stock"),
    ("ok", "promote"),
])
def test_rising_matrix(stock_status, expected_action):
    result = recommend_action(matched("rising"), stock_status, 10)
    assert result["action"] == expected_action


@pytest.mark.parametrize("stock_status", ["critical", "low", "ok"])
def test_falling_always_discounts(stock_status):
    result = recommend_action(matched("falling"), stock_status, 20)
    assert result["action"] == "discount"
    assert "Sneakers" in result["reason"]


@pytest.mark.parametrize("classification", ["steady", "new"])
@pytest.mark.parametrize("stock_status,expected_action", [
    ("critical", "reduce_reorder_risk"),
    ("low", "reduce_reorder_risk"),
    ("ok", "none"),
])
def test_steady_and_new_defer_to_stock_level(classification, stock_status, expected_action):
    result = recommend_action(matched(classification), stock_status, 3)
    assert result["action"] == expected_action


@pytest.mark.parametrize("stock_status,expected_action", [
    ("critical", "reduce_reorder_risk"),
    ("low", "reduce_reorder_risk"),
    ("ok", "none"),
])
def test_unmatched_product_defers_to_stock_level(stock_status, expected_action):
    result = recommend_action([], stock_status, 4)
    assert result["action"] == expected_action
    assert "not matched" in result["reason"].lower()


def test_reason_always_cites_days_remaining():
    result = recommend_action([], "ok", 42.5)
    assert "42.5" in result["reason"]


def test_multiple_matched_trends_picks_highest_priority_classification():
    trends = [
        {"trend": "steady one", "classification": "steady", "score": 0.9},
        {"trend": "spiking one", "classification": "spiking", "score": 0.5},
    ]
    result = recommend_action(trends, "ok", 20)
    assert result["action"] == "promote"
    assert "spiking one" in result["reason"]
