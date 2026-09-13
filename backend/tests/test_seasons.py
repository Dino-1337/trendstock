"""Recurring demand periods.

These exist because a calendar API only knows dated points. Verified concretely:
a bridal saree with 1.4 days of stock raised no warning, because every festival
in range was `festive` and nothing on the calendar is `wedding`.
"""

import json
from datetime import date

import pytest

from app.events import seasons
from app.events.models import EventType


@pytest.fixture
def seasons_file(tmp_path):
    path = tmp_path / "seasons.json"
    path.write_text(json.dumps({
        "version": "test",
        "seasons": [
            {"name": "Wedding season", "start": "11-01", "end": "02-28",
             "regions": ["North India"]},
            {"name": "Monsoon", "start": "06-15", "end": "09-15", "regions": []},
            {"name": "Summer", "start": "03-15", "end": "06-15", "regions": []},
        ],
    }), encoding="utf-8")
    return path


# --- span membership ------------------------------------------------------

def test_a_normal_span_contains_its_middle():
    assert seasons._is_active((6, 15), (9, 15), date(2026, 7, 1)) is True


def test_a_normal_span_excludes_outside_dates():
    assert seasons._is_active((6, 15), (9, 15), date(2026, 10, 1)) is False


def test_a_span_includes_its_boundaries():
    assert seasons._is_active((6, 15), (9, 15), date(2026, 6, 15)) is True
    assert seasons._is_active((6, 15), (9, 15), date(2026, 9, 15)) is True


@pytest.mark.parametrize("today", [date(2026, 12, 15), date(2026, 1, 15), date(2026, 11, 1)])
def test_a_year_wrapping_span_is_active_across_new_year(today):
    # Wedding season runs 11-01 to 02-28, so its end month is numerically
    # before its start. Comparing naively would make it never active.
    assert seasons._is_active((11, 1), (2, 28), today) is True


@pytest.mark.parametrize("today", [date(2026, 6, 1), date(2026, 3, 15)])
def test_a_year_wrapping_span_excludes_the_middle_of_the_year(today):
    assert seasons._is_active((11, 1), (2, 28), today) is False


# --- next occurrence ------------------------------------------------------

def test_an_upcoming_start_stays_in_this_year():
    assert seasons._next_occurrence(11, 1, date(2026, 9, 13)) == date(2026, 11, 1)


def test_a_passed_start_rolls_to_next_year():
    # Otherwise wedding season would read as permanently expired from
    # December onward.
    assert seasons._next_occurrence(3, 15, date(2026, 9, 13)) == date(2027, 3, 15)


def test_a_start_today_counts_as_upcoming():
    assert seasons._next_occurrence(9, 13, date(2026, 9, 13)) == date(2026, 9, 13)


def test_leap_day_falls_back_to_the_28th_in_a_non_leap_year():
    # 2027 has no 29 February, so the honest neighbour is the 28th.
    assert seasons._next_occurrence(2, 29, date(2026, 3, 1)) == date(2027, 2, 28)


def test_leap_day_is_kept_when_the_year_has_one():
    assert seasons._next_occurrence(2, 29, date(2027, 3, 1)) == date(2028, 2, 29)


# --- loading --------------------------------------------------------------

def test_seasons_load_as_calendar_events(seasons_file):
    events = seasons.load_seasons(date(2026, 9, 13), path=seasons_file)
    assert len(events) == 3
    assert all(e.event_type is EventType.SEASONAL for e in events)


def test_seasons_record_their_source(seasons_file):
    events = seasons.load_seasons(date(2026, 9, 13), path=seasons_file)
    assert all(e.source == seasons.SOURCE for e in events)


def test_seasons_are_sorted_by_date(seasons_file):
    events = seasons.load_seasons(date(2026, 9, 13), path=seasons_file)
    assert [e.event_date for e in events] == sorted(e.event_date for e in events)


def test_regions_are_preserved(seasons_file):
    events = seasons.load_seasons(date(2026, 9, 13), path=seasons_file)
    wedding = next(e for e in events if e.name == "Wedding season")
    assert wedding.regions == ["North India"] and wedding.is_regional


def test_an_active_season_is_anchored_to_a_past_start(seasons_file):
    # A seller already inside monsoon needs it surfaced, not reported as
    # starting in 280 days.
    events = seasons.load_seasons(date(2026, 7, 1), path=seasons_file)
    monsoon = next(e for e in events if e.name == "Monsoon")
    assert monsoon.event_date == date(2026, 6, 15)
    assert monsoon.days_until(date(2026, 7, 1)) < 0


def test_an_upcoming_season_is_dated_forward(seasons_file):
    events = seasons.load_seasons(date(2026, 9, 13), path=seasons_file)
    wedding = next(e for e in events if e.name == "Wedding season")
    assert wedding.event_date == date(2026, 11, 1)


def test_horizon_filters_distant_seasons(seasons_file):
    names = {e.name for e in seasons.load_seasons(
        date(2026, 9, 13), path=seasons_file, within_days=30
    )}
    assert "Wedding season" not in names  # 49 days out


def test_an_active_season_survives_the_horizon(seasons_file):
    # It is happening now; a forward-looking window must not hide it.
    names = {e.name for e in seasons.load_seasons(
        date(2026, 7, 1), path=seasons_file, within_days=1
    )}
    assert "Monsoon" in names


def test_active_seasons_returns_only_current_ones(seasons_file):
    names = {e.name for e in seasons.active_seasons(date(2026, 7, 1), path=seasons_file)}
    assert names == {"Monsoon"}


def test_missing_file_is_not_an_error(tmp_path):
    assert seasons.load_seasons(date(2026, 9, 13), path=tmp_path / "nope.json") == []


def test_incomplete_entries_are_skipped(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"seasons": [
        {"name": "No dates"},
        {"start": "01-01", "end": "02-01"},
        {"name": "Good", "start": "11-01", "end": "12-01"},
    ]}), encoding="utf-8")
    assert [e.name for e in seasons.load_seasons(date(2026, 9, 13), path=path)] == ["Good"]


# --- the real file --------------------------------------------------------

def test_the_shipped_file_parses():
    events = seasons.load_seasons(date(2026, 9, 13))
    assert events, "the curated seasons file should yield events"


def test_the_shipped_file_covers_wedding_season():
    # The specific gap this module exists to close.
    names = " ".join(e.name.lower() for e in seasons.load_seasons(date(2026, 9, 13)))
    assert "wedding" in names
