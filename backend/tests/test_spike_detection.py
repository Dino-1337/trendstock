from datetime import date, timedelta
from pathlib import Path
import json

import pytest

from app.store_trend.process_raw_data import compute_series_metrics

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "trend_scenarios.json"


def as_series(values):
    """Shape a bare value list like a real Google Trends weekly series."""
    start = date.today() - timedelta(weeks=len(values))
    return [
        {
            "date": (start + timedelta(weeks=i)).isoformat(),
            "value": value,
            "is_partial": False,
        }
        for i, value in enumerate(values)
    ]


def load_scenarios():
    with open(FIXTURES) as f:
        return json.load(f)


@pytest.mark.parametrize("scenario", load_scenarios(), ids=lambda s: s["scenario"])
def test_scenario_classification(scenario):
    metrics = compute_series_metrics(as_series(scenario["values"]))
    assert metrics["classification"] == scenario["expected_classification"]


def test_partial_points_are_ignored():
    series = as_series([30] * 12)
    series.append({"date": "2026-08-05", "value": 1, "is_partial": True})
    metrics = compute_series_metrics(series)
    assert metrics["latest_value"] == 30


def test_too_short_series_returns_none():
    assert compute_series_metrics(as_series([10, 12, 11, 13])) is None
