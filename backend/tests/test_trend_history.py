"""Section C: trend history built by accumulating daily snapshots.

All synthetic in-memory - no filesystem, no network - per the "no network
calls in tests" constraint.
"""

from app.store_trend.trend_history import (
    classify_series,
    daily_classification_counts,
    slugify,
)


def test_single_snapshot_is_new_with_null_momentum():
    metrics = classify_series([("2026-08-05", 500)])
    assert metrics == {"classification": "new", "momentum_pct": None, "spike_ratio": None}


def test_two_snapshots_spike_ratio_over_threshold_is_spiking():
    series = [("2026-08-04", 100), ("2026-08-05", 250)]
    metrics = classify_series(series)
    assert metrics["classification"] == "spiking"
    assert metrics["spike_ratio"] == 2.5
    assert metrics["momentum_pct"] == 150.0


def test_moderate_increase_is_rising():
    series = [("2026-08-04", 100), ("2026-08-05", 120)]
    metrics = classify_series(series)
    assert metrics["classification"] == "rising"
    assert metrics["momentum_pct"] == 20.0


def test_moderate_decrease_is_falling():
    series = [("2026-08-04", 100), ("2026-08-05", 80)]
    metrics = classify_series(series)
    assert metrics["classification"] == "falling"
    assert metrics["momentum_pct"] == -20.0


def test_flat_is_steady():
    series = [("2026-08-04", 100), ("2026-08-05", 105)]
    metrics = classify_series(series)
    assert metrics["classification"] == "steady"


def test_longer_series_uses_median_baseline_not_just_prior_point():
    # Prior point alone would look flat (100 -> 105, momentum only 5%), but a
    # baseline built from the whole history should still catch the earlier dip.
    series = [("d1", 20), ("d2", 20), ("d3", 20), ("d4", 100), ("d5", 105)]
    metrics = classify_series(series)
    assert metrics["spike_ratio"] == 5.25  # 105 / median([20,20,20,100]) = 105/20


def test_slugify_handles_non_ascii_without_collapsing_to_empty():
    # Most of this feed's trends are Hindi/Bengali/Telugu - stripping non-ASCII
    # would collapse every one of them to the same slug and collide on id.
    assert slugify("ईशान किशन") != slugify("पाकिस्तान")
    assert slugify("ईशान किशन") != ""
    assert slugify("The Mummy 4") == "the-mummy-4"


def test_daily_classification_counts_is_causal_not_lookahead():
    """A trend that spikes on day 3 must not count as spiking on day 1 or 2 -
    each day's counts may only use data available up to and including that day."""
    raw_dir_snapshots = {
        "2026-08-01": {"t1": {"trend": "t1", "traffic_min": 100, "published": None}},
        "2026-08-02": {"t1": {"trend": "t1", "traffic_min": 100, "published": None}},
        "2026-08-03": {"t1": {"trend": "t1", "traffic_min": 400, "published": None}},
    }

    import app.store_trend.trend_history as th

    original_loader = th.load_raw_snapshots
    th.load_raw_snapshots = lambda raw_dir=None: raw_dir_snapshots
    try:
        points = daily_classification_counts()
    finally:
        th.load_raw_snapshots = original_loader

    assert points[0] == {"date": "2026-08-01", "spiking": 0, "rising": 0, "steady": 0}
    assert points[1]["spiking"] == 0
    assert points[2]["spiking"] == 1
