"""Signal interpretation, storage, and matching.

The LLM and Exa are always stubbed. What is exercised for real is the scoring,
the occasion join, and the persistence round-trip.
"""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.enrichment.models import Audience, EnrichedProduct
from app.events.models import Evidence, EvidenceKind, Level
from app.llm import client as llm
from app.signals import interpreter, matcher
from app.signals.models import Phase, Signal, SignalInterpretationLLM, SignalType
from app.storage import db

TODAY = date(2026, 9, 13)
DIWALI = date(2026, 11, 8)


@pytest.fixture
def conn(tmp_path):
    connection = db.init_db(db.connect(tmp_path / "t.db"))
    yield connection
    connection.close()


def signal(**overrides):
    defaults = {
        "signal_type": SignalType.EVENT,
        "name": "Diwali",
        "event_date": DIWALI,
        "affected_occasions": ["festive", "gifting"],
        "affected_categories": ["Saris"],
        "demand_lift": Level.HIGH,
        "confidence": Level.HIGH,
        "lead_time_days": 30,
        "reasoning": "Diwali drives festive apparel.",
        "phase": Phase.BULK,
    }
    return Signal(**{**defaults, **overrides})


def enriched(pid="p1", title="Banarasi Saree", occasions=("festive",),
             categories=("Saris",), audience=None):
    return EnrichedProduct(
        product_id=pid, title=title, occasions=list(occasions),
        categories=list(categories), audience=audience,
    )


# --- strict interpretation schema ----------------------------------------

def test_interpretation_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        SignalInterpretationLLM(relevant=True, reasoning="x", invented=1)


def test_interpretation_canonicalizes_occasions():
    # "Diwali" must never reach storage as an occasion; it is an event name.
    result = SignalInterpretationLLM(relevant=True, reasoning="x",
                                     affected_occasions=["Diwali", "Gifts"])
    assert result.affected_occasions == ["festive", "gifting"]


def test_interpretation_drops_unmappable_occasions():
    result = SignalInterpretationLLM(relevant=True, reasoning="x",
                                     affected_occasions=["moon landing"])
    assert result.affected_occasions == []


def test_blank_reasoning_normalises_to_none():
    # Reasoning is optional on purpose: models answer a rejection with a bare
    # {"relevant": false}, and requiring an explanation cost a whole batch of
    # ten events to validation failure.
    assert SignalInterpretationLLM(relevant=False, reasoning="   ").reasoning is None


def test_a_rejection_needs_no_reasoning():
    assert SignalInterpretationLLM(relevant=False).relevant is False


def test_interpretation_rejects_absurd_lead_time():
    with pytest.raises(ValidationError):
        SignalInterpretationLLM(relevant=True, reasoning="x", lead_time_days=9999)


def test_relevant_without_occasions_is_not_actionable():
    # Worse than being dropped: it would show as a live signal that silently
    # affects zero products.
    result = SignalInterpretationLLM(relevant=True, reasoning="x", affected_occasions=[])
    assert result.relevant is True and result.is_actionable is False


def test_relevant_with_occasions_is_actionable():
    result = SignalInterpretationLLM(relevant=True, reasoning="x",
                                     affected_occasions=["festive"])
    assert result.is_actionable is True


# --- lead window ----------------------------------------------------------

def test_event_outside_lead_window():
    # Diwali is 56 days out with a 30-day lead time.
    assert signal().is_in_lead_window(TODAY) is False


def test_event_inside_lead_window():
    assert signal(lead_time_days=60).is_in_lead_window(TODAY) is True


def test_past_event_is_out_of_window():
    assert signal(event_date=date(2026, 9, 1)).is_in_lead_window(TODAY) is False


def test_undated_trend_is_always_in_window():
    # A viral trend is happening now; there is no lead time to wait for.
    trend = signal(signal_type=SignalType.TREND, name="coquette", event_date=None)
    assert trend.is_in_lead_window(TODAY) is True
    assert trend.days_until(TODAY) is None


# --- scoring --------------------------------------------------------------

def test_no_occasion_overlap_scores_zero():
    # The hard requirement: without it a festival would weakly "match" the
    # entire catalog and ranking would be noise.
    value, reasons = matcher.score(signal(), enriched(occasions=["sport_active"]))
    assert value == 0.0 and reasons == []


def test_single_occasion_overlap_matches():
    value, _ = matcher.score(signal(), enriched(categories=[]))
    assert value >= matcher.MIN_SCORE


def test_more_occasion_overlap_scores_higher():
    one, _ = matcher.score(signal(), enriched(occasions=["festive"], categories=[]))
    two, _ = matcher.score(signal(), enriched(occasions=["festive", "gifting"], categories=[]))
    assert two > one


def test_category_overlap_is_a_bonus():
    without, _ = matcher.score(signal(), enriched(categories=["Jackets"]))
    with_cat, _ = matcher.score(signal(), enriched(categories=["Saris"]))
    assert with_cat > without


def test_category_is_not_required():
    # Requiring it would reintroduce the old failure: "Diwali" names no
    # category at all.
    value, _ = matcher.score(signal(affected_categories=[]), enriched(categories=[]))
    assert value >= matcher.MIN_SCORE


def test_matching_audience_is_a_bonus():
    base, _ = matcher.score(signal(), enriched(audience=None))
    same, _ = matcher.score(signal(audience="women"), enriched(audience=Audience.WOMEN))
    assert same > base


def test_conflicting_audience_is_penalised_not_vetoed():
    value, reasons = matcher.score(signal(audience="men"), enriched(audience=Audience.WOMEN))
    assert value > 0, "a mismatch demotes, it does not hide - gifting exists"
    assert any("mismatch" in r for r in reasons)


def test_unisex_never_conflicts():
    value, reasons = matcher.score(signal(audience="unisex"), enriched(audience=Audience.WOMEN))
    assert not any("mismatch" in r for r in reasons)


def test_score_is_capped_at_one():
    value, _ = matcher.score(
        signal(audience="women"),
        enriched(occasions=["festive", "gifting"], categories=["Saris"], audience=Audience.WOMEN),
    )
    assert value <= 1.0


def test_reasons_explain_the_match():
    _, reasons = matcher.score(signal(), enriched())
    assert any("occasion" in r for r in reasons)


# --- matching -------------------------------------------------------------

PRODUCTS = [
    enriched("p1", "Banarasi Saree", ["festive"], ["Saris"]),
    enriched("p2", "Kanjivaram Saree", ["wedding", "bridal"], ["Saris"]),
    enriched("p3", "Running Shoes", ["sport_active"], ["Sneakers"]),
]


def test_match_signal_returns_only_relevant_products():
    ids = [m["product_id"] for m in matcher.match_signal(signal(), PRODUCTS)]
    assert ids == ["p1"]


def test_match_signal_is_sorted_best_first():
    matches = matcher.match_signal(
        signal(), [enriched("a", "A", ["festive"], []), enriched("b", "B", ["festive"], ["Saris"])]
    )
    assert matches[0]["product_id"] == "b"


def test_irrelevant_signal_matches_nothing():
    assert matcher.match_signal(signal(relevant=False), PRODUCTS) == []


def test_signal_without_occasions_matches_nothing():
    assert matcher.match_signal(signal(affected_occasions=[]), PRODUCTS) == []


def test_match_all_sorts_by_urgency():
    soon = signal(name="Navratri", event_date=date(2026, 10, 11))
    later = signal(name="Diwali", event_date=DIWALI)
    result = matcher.match_all([later, soon], PRODUCTS, today=TODAY)
    assert [e["signal"].name for e in result] == ["Navratri", "Diwali"]


def test_undated_trends_sort_after_dated_events():
    trend = signal(signal_type=SignalType.TREND, name="coquette", event_date=None)
    result = matcher.match_all([trend, signal()], PRODUCTS, today=TODAY)
    assert result[-1]["signal"].name == "coquette"


def test_in_window_only_filters_distant_events():
    assert matcher.match_all([signal()], PRODUCTS, today=TODAY, in_window_only=True) == []


# --- stockout warnings ----------------------------------------------------

LOOKUP = {
    "p1": {"days_stock_remaining": 3.0, "current_stock": 6},
    "p2": {"days_stock_remaining": 40.0, "current_stock": 90},
}


def test_only_low_cover_products_become_warnings():
    # A matched product with plenty of cover needs no action.
    matched = matcher.match_all([signal()], PRODUCTS, today=TODAY)
    warnings = matcher.products_at_risk(matched, LOOKUP)
    assert [w["product_id"] for w in warnings] == ["p1"]


def test_warnings_are_sorted_by_urgency():
    products = [enriched("p1", "A", ["festive"]), enriched("p2", "B", ["festive"])]
    lookup = {"p1": {"days_stock_remaining": 9.0}, "p2": {"days_stock_remaining": 2.0}}
    matched = matcher.match_all([signal()], products, today=TODAY)
    assert [w["product_id"] for w in matcher.products_at_risk(matched, lookup)] == ["p2", "p1"]


def test_a_product_is_warned_about_once_by_its_soonest_signal():
    # Listing the same saree once per festival would bury the catalog.
    soon = signal(name="Navratri", event_date=date(2026, 10, 11))
    later = signal(name="Diwali", event_date=DIWALI)
    matched = matcher.match_all([later, soon], PRODUCTS, today=TODAY)
    warnings = matcher.products_at_risk(matched, LOOKUP)
    assert len(warnings) == 1 and warnings[0]["signal_name"] == "Navratri"


def test_warning_carries_why_it_was_raised():
    matched = matcher.match_all([signal()], PRODUCTS, today=TODAY)
    warning = matcher.products_at_risk(matched, LOOKUP)[0]
    assert warning["demand_lift"] == "high" and warning["reasons"]


# --- persistence ----------------------------------------------------------

def test_save_and_load_roundtrips(conn):
    interpreter.save_signal(conn, signal())
    loaded = interpreter.load_signals(conn)
    assert len(loaded) == 1
    assert loaded[0].affected_occasions == ["festive", "gifting"]
    assert loaded[0].demand_lift is Level.HIGH
    assert loaded[0].event_date == DIWALI


def test_resaving_updates_in_place(conn):
    interpreter.save_signal(conn, signal())
    interpreter.save_signal(conn, signal(demand_lift=Level.LOW))
    loaded = interpreter.load_signals(conn)
    assert len(loaded) == 1 and loaded[0].demand_lift is Level.LOW


def test_irrelevant_signals_are_stored_but_filtered(conn):
    # Kept for auditability - "why was this dropped" is a real question.
    interpreter.save_signal(conn, signal(name="Halloween", relevant=False))
    assert interpreter.load_signals(conn, only_relevant=True) == []
    assert len(interpreter.load_signals(conn, only_relevant=False)) == 1


def test_evidence_roundtrips(conn):
    with_evidence = signal(evidence=[Evidence(
        kind=EvidenceKind.SEARCH_RESULT, url="https://example.com",
        title="Diwali demand", snippet="peaks 30 days before",
        retrieved_at=datetime(2026, 9, 13, tzinfo=timezone.utc), cache_key="k1",
    )])
    interpreter.save_signal(conn, with_evidence)
    loaded = interpreter.load_signals(conn)[0]
    assert len(loaded.evidence) == 1
    assert loaded.evidence[0].cache_key == "k1"


def test_a_refresh_replaces_stale_evidence(conn):
    interpreter.save_signal(conn, signal(evidence=[Evidence(
        kind=EvidenceKind.SEARCH_RESULT, url="https://old.example.com",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )]))
    interpreter.save_signal(conn, signal(evidence=[Evidence(
        kind=EvidenceKind.SEARCH_RESULT, url="https://new.example.com",
        retrieved_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )]))
    loaded = interpreter.load_signals(conn)[0]
    assert [e.url for e in loaded.evidence] == ["https://new.example.com"]


def test_undated_trend_persists(conn):
    interpreter.save_signal(conn, signal(
        signal_type=SignalType.TREND, name="coquette", event_date=None
    ))
    loaded = interpreter.load_signals(conn, signal_type=SignalType.TREND)
    assert len(loaded) == 1 and loaded[0].event_date is None


# --- interpretation flow --------------------------------------------------

def test_interpret_maps_plain_categories_onto_the_vocabulary(monkeypatch):
    # The model is asked for plain words ("sarees") rather than exact taxonomy
    # names, because inlining the 465-term list blew the TPM budget.
    monkeypatch.setattr(llm, "structured", lambda *a, **k: SignalInterpretationLLM(
        relevant=True, reasoning="x", affected_occasions=["festive"],
        affected_categories=["sarees", "kurtis"],
    ))
    result = interpreter.interpret("Diwali", SignalType.EVENT, "a store")
    assert "Saris" in result.affected_categories
    assert "Kurtas & Kurta Sets" in result.affected_categories


def batch(per_index):
    """Batch response from {index: payload}; a dict positionally, because
    integer keys are not valid keyword names."""
    from app.signals.models import SignalInterpretationBatchLLM

    return SignalInterpretationBatchLLM(signals={
        str(i): SignalInterpretationLLM(**p) for i, p in per_index.items()
    })


def calendar_events(*names):
    from app.events.models import CalendarEvent

    return [CalendarEvent(name=n, event_date=DIWALI) for n in names]


def test_bulk_interpretation_is_batched(monkeypatch):
    # One call per event exhausts Groq's free tier on a full calendar year;
    # batching is a rate-limit measure, not an optimisation.
    sizes = []

    def fake(messages, model_cls, **kwargs):
        sizes.append(messages[0]["content"].count("\n0:") + messages[0]["content"].count("\n1:"))
        return batch({i: {"relevant": True, "reasoning": "x",
                          "affected_occasions": ["festive"]} for i in range(10)})

    monkeypatch.setattr(llm, "structured", fake)
    interpreter.interpret_events(calendar_events(*[f"E{i}" for i in range(25)]),
                                 "a store", TODAY, batch_size=10)
    assert len(sizes) == 3, "25 events should take 3 batched calls, not 25"


def test_a_failing_batch_does_not_cost_the_other_batches(monkeypatch):
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return batch({0: {"relevant": True, "reasoning": "x",
                          "affected_occasions": ["festive"]}})

    monkeypatch.setattr(llm, "structured", flaky)
    signals = interpreter.interpret_events(
        calendar_events("Bad", "Good"), "a store", TODAY, batch_size=1
    )
    assert [s.name for s in signals] == ["Good"]


def test_a_vacuous_batch_is_skipped(monkeypatch):
    from app.signals.models import SignalInterpretationBatchLLM

    monkeypatch.setattr(llm, "structured",
                        lambda *a, **k: SignalInterpretationBatchLLM(signals={}))
    assert interpreter.interpret_events(calendar_events("A"), "a store", TODAY) == []


def test_an_invented_batch_index_is_ignored(monkeypatch):
    monkeypatch.setattr(llm, "structured", lambda *a, **k: batch(
        {99: {"relevant": True, "reasoning": "x", "affected_occasions": ["festive"]}}
    ))
    assert interpreter.interpret_events(calendar_events("A"), "a store", TODAY) == []


def test_refresh_falls_back_to_per_event(monkeypatch):
    # Each refresh needs its own search, so it cannot be batched. That is fine:
    # refresh runs for one event entering its window, not the whole year.
    from app.research import exa_client

    monkeypatch.setattr(exa_client, "is_available", lambda: False)
    calls = []

    def fake(*args, **kwargs):
        calls.append(1)
        return SignalInterpretationLLM(relevant=True, reasoning="x",
                                       affected_occasions=["festive"])

    monkeypatch.setattr(llm, "structured", fake)
    interpreter.interpret_events(calendar_events("A", "B"), "a store", TODAY,
                                 phase=Phase.REFRESH)
    assert len(calls) == 2


def test_bulk_phase_does_not_search(monkeypatch):
    from app.research import exa_client

    monkeypatch.setattr(exa_client, "is_available", lambda: True)
    monkeypatch.setattr(exa_client, "search",
                        lambda *a, **k: pytest.fail("bulk must not search"))
    monkeypatch.setattr(llm, "structured", lambda *a, **k: SignalInterpretationLLM(
        relevant=True, reasoning="x", affected_occasions=["festive"],
    ))
    interpreter.interpret("Diwali", SignalType.EVENT, "a store", phase=Phase.BULK)


def test_refresh_survives_a_search_failure(monkeypatch):
    # A missing citation is much better than no signal.
    from app.research import exa_client

    monkeypatch.setattr(exa_client, "is_available", lambda: True)
    monkeypatch.setattr(exa_client, "search",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(llm, "structured", lambda *a, **k: SignalInterpretationLLM(
        relevant=True, reasoning="x", affected_occasions=["festive"],
    ))
    result = interpreter.interpret("Diwali", SignalType.EVENT, "a store", phase=Phase.REFRESH)
    assert result.relevant is True and result.evidence == []
