from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.events.models import (
    CalendarEvent,
    CategoryEventSignal,
    CategorySignalBatchLLM,
    CategorySignalLLM,
    Evidence,
    EvidenceKind,
    EventType,
    Level,
    Phase,
)

TODAY = date(2026, 9, 13)
DIWALI = date(2026, 11, 8)


def make_event(**overrides):
    defaults = {"name": "Diwali", "event_date": DIWALI, "event_type": EventType.NATIONAL}
    return CalendarEvent(**{**defaults, **overrides})


def make_signal_payload(**overrides):
    defaults = {
        "category": "Ethnic Wear",
        "event_name": "Diwali",
        "demand_lift": "high",
        "confidence": "high",
        "lead_time_days": 35,
        "reasoning_summary": "Diwali drives ethnic wear purchases.",
    }
    return {**defaults, **overrides}


# --- CalendarEvent --------------------------------------------------------

def test_event_with_no_regions_is_not_regional():
    assert make_event().is_regional is False


def test_event_with_regions_is_regional():
    assert make_event(name="Onam", regions=["Kerala"]).is_regional is True


def test_days_until_counts_forward():
    assert make_event().days_until(TODAY) == 56


def test_days_until_goes_negative_after_the_event():
    assert make_event(event_date=date(2026, 9, 1)).days_until(TODAY) == -12


def test_date_is_estimated_defaults_false():
    assert make_event().date_is_estimated is False


def test_lunar_events_can_flag_date_uncertainty():
    assert make_event(date_is_estimated=True).date_is_estimated is True


def test_event_name_cannot_be_empty():
    with pytest.raises(ValidationError):
        CalendarEvent(name="", event_date=DIWALI)


def test_event_date_accepts_iso_string():
    assert CalendarEvent(name="Holi", event_date="2026-03-04").event_date == date(2026, 3, 4)


def test_event_date_rejects_nonsense():
    with pytest.raises(ValidationError):
        CalendarEvent(name="Holi", event_date="not-a-date")


def test_unicode_event_names_survive():
    assert CalendarEvent(name="दिवाली", event_date=DIWALI).name == "दिवाली"


# --- CategorySignalLLM (strict, model-facing) -----------------------------

def test_valid_llm_signal_parses():
    signal = CategorySignalLLM(**make_signal_payload())
    assert (signal.demand_lift, signal.confidence) == (Level.HIGH, Level.HIGH)


def test_llm_signal_rejects_unknown_fields():
    # A hallucinated field must fail loudly rather than be silently dropped.
    with pytest.raises(ValidationError):
        CategorySignalLLM(**make_signal_payload(estimated_revenue="₹50000"))


def test_llm_signal_rejects_invalid_level():
    with pytest.raises(ValidationError):
        CategorySignalLLM(**make_signal_payload(demand_lift="enormous"))


def test_llm_signal_rejects_negative_lead_time():
    with pytest.raises(ValidationError):
        CategorySignalLLM(**make_signal_payload(lead_time_days=-1))


def test_llm_signal_rejects_absurd_lead_time():
    with pytest.raises(ValidationError):
        CategorySignalLLM(**make_signal_payload(lead_time_days=400))


def test_llm_signal_rejects_whitespace_only_category():
    with pytest.raises(ValidationError):
        CategorySignalLLM(**make_signal_payload(category="   "))


def test_llm_signal_strips_surrounding_whitespace():
    assert CategorySignalLLM(**make_signal_payload(category="  Ethnic Wear  ")).category == "Ethnic Wear"


def test_llm_signal_rejects_empty_reasoning():
    with pytest.raises(ValidationError):
        CategorySignalLLM(**make_signal_payload(reasoning_summary=""))


# --- CategorySignalBatchLLM ----------------------------------------------

def test_batch_parses_multiple_signals():
    batch = CategorySignalBatchLLM(
        signals=[make_signal_payload(), make_signal_payload(category="Jewelry")]
    )
    assert len(batch.signals) == 2


def test_empty_batch_is_vacuous():
    # The documented failure mode: a successful, schema-valid, useless response.
    assert CategorySignalBatchLLM(signals=[]).is_vacuous is True


def test_missing_signals_key_is_vacuous_rather_than_an_error():
    assert CategorySignalBatchLLM().is_vacuous is True


def test_populated_batch_is_not_vacuous():
    assert CategorySignalBatchLLM(signals=[make_signal_payload()]).is_vacuous is False


def test_batch_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        CategorySignalBatchLLM(signals=[], notes="none found")


def test_one_bad_signal_fails_the_whole_batch():
    with pytest.raises(ValidationError):
        CategorySignalBatchLLM(
            signals=[make_signal_payload(), make_signal_payload(demand_lift="???")]
        )


# --- CategoryEventSignal (stored) ----------------------------------------

def make_stored(**overrides):
    defaults = {
        "category": "Ethnic Wear",
        "event": make_event(),
        "lead_time_days": 35,
        "phase": Phase.BULK,
    }
    return CategoryEventSignal(**{**defaults, **overrides})


def test_stored_signal_exposes_days_until_event():
    assert make_stored().days_until_event(TODAY) == 56


def test_event_outside_lead_window_is_not_actionable():
    # Diwali is 56 days out with a 35-day lead time: not yet.
    assert make_stored().is_in_lead_window(TODAY) is False


def test_event_inside_lead_window_is_actionable():
    assert make_stored(lead_time_days=60).is_in_lead_window(TODAY) is True


def test_event_exactly_at_lead_time_is_actionable():
    assert make_stored(lead_time_days=56).is_in_lead_window(TODAY) is True


def test_past_event_is_not_actionable():
    past = make_stored(event=make_event(event_date=date(2026, 9, 1)), lead_time_days=35)
    assert past.is_in_lead_window(TODAY) is False


def test_signal_without_lead_time_is_not_actionable():
    assert make_stored(lead_time_days=None).is_in_lead_window(TODAY) is False


def test_stored_signal_defaults_to_no_evidence():
    assert make_stored().evidence == []


def test_stored_signal_carries_evidence():
    evidence = Evidence(
        kind=EvidenceKind.SEARCH_RESULT,
        url="https://example.com/diwali-retail",
        title="Diwali retail trends",
        snippet="Ethnic wear demand rises ~5 weeks out.",
        retrieved_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
        cache_key="abc123",
    )
    assert make_stored(evidence=[evidence]).evidence[0].cache_key == "abc123"


def test_phase_records_how_the_signal_was_produced():
    assert make_stored(phase=Phase.EVENT_REFRESH).phase is Phase.EVENT_REFRESH


def test_phase_rejects_unknown_value():
    with pytest.raises(ValidationError):
        make_stored(phase="guessed")
