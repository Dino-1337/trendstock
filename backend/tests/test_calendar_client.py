"""Calendarific client tests. All HTTP is stubbed - the free tier is only 500
requests/month, so the suite must never touch the network.

Fixture values are copied from a real India 2026 response.
"""

from datetime import date

import pytest

from app.events import calendar_client as cal
from app.events.models import EventType
from app.storage import db


def holiday(name="Diwali/Deepavali", iso="2026-11-08", primary="Gazetted Holiday",
            types=("National holiday", "Hinduism"), states="All"):
    return {
        "name": name,
        "date": {"iso": iso, "datetime": {"year": 2026, "month": 11, "day": 8}},
        "primary_type": primary,
        "type": list(types),
        "states": states,
        "locations": "All",
    }


def payload(*holidays):
    return {"meta": {"code": 200}, "response": {"holidays": list(holidays)}}


SAMPLE = payload(
    holiday(),
    holiday(name="Onam", iso="2026-08-26", primary="Restricted Holiday",
            types=("Optional holiday",)),
    holiday(name="September Equinox", iso="2026-09-23", primary="Season",
            types=("Season",)),
)


@pytest.fixture
def conn(tmp_path):
    connection = db.init_db(db.connect(tmp_path / "t.db"))
    yield connection
    connection.close()


@pytest.fixture
def spy(monkeypatch):
    calls = []
    monkeypatch.setattr(cal, "calendarific_api_key", lambda: "test-key")

    def _get(params, api_key):
        calls.append((params, api_key))
        return SAMPLE

    monkeypatch.setattr(cal, "_get", _get)
    return calls


# --- request building -----------------------------------------------------

def test_request_carries_country_and_year():
    params = cal.build_request(year=2026)
    assert params["country"] == "IN" and params["year"] == 2026


def test_request_excludes_the_api_key():
    # The key is authentication, not part of the question - including it would
    # make rotating the key invalidate every cached year for nothing.
    assert "api_key" not in cal.build_request(year=2026)


def test_request_omits_optional_filters_by_default():
    params = cal.build_request(year=2026)
    assert "location" not in params and "type" not in params


def test_request_includes_optional_filters_when_given():
    params = cal.build_request(year=2026, location="in-kl", holiday_type="national")
    assert params["location"] == "in-kl" and params["type"] == "national"


# --- error handling -------------------------------------------------------

def test_fetch_raises_without_key(monkeypatch):
    monkeypatch.setattr(cal, "calendarific_api_key", lambda: None)
    with pytest.raises(cal.CalendarificError):
        cal.fetch_year(2026)


def test_error_payload_raises_even_on_http_200(monkeypatch):
    # Calendarific answers auth failures with HTTP 200 and a non-200 meta.code.
    # Without this check an expired key would look like "no holidays exist".
    monkeypatch.setattr(cal, "calendarific_api_key", lambda: "k")
    monkeypatch.setattr(
        cal, "requests",
        type("R", (), {"get": staticmethod(lambda *a, **k: type("Resp", (), {
            "raise_for_status": lambda self: None,
            "json": lambda self: {"meta": {"code": 401, "error_type": "auth failed",
                                           "error_detail": "invalid key"}},
        })())})
    )
    with pytest.raises(cal.CalendarificError, match="401"):
        cal.fetch_year(2026)


# --- caching --------------------------------------------------------------

def test_first_fetch_hits_the_api(conn, spy):
    _, key, cached = cal.fetch_year(2026, conn=conn)
    assert cached is False and key and len(spy) == 1


def test_repeat_fetch_is_served_from_cache(conn, spy):
    cal.fetch_year(2026, conn=conn)
    response, _, cached = cal.fetch_year(2026, conn=conn)
    assert (response, cached) == (SAMPLE, True)
    assert len(spy) == 1, "a whole country-year must cost one request, not two"


def test_different_year_is_a_separate_entry(conn, spy):
    cal.fetch_year(2026, conn=conn)
    cal.fetch_year(2027, conn=conn)
    assert len(spy) == 2


def test_rotating_the_key_does_not_invalidate_the_cache(conn, spy, monkeypatch):
    cal.fetch_year(2026, conn=conn)
    monkeypatch.setattr(cal, "calendarific_api_key", lambda: "rotated")
    _, _, cached = cal.fetch_year(2026, conn=conn)
    assert cached is True


# --- parsing --------------------------------------------------------------

def test_to_events_parses_every_holiday():
    assert len(cal.to_events(SAMPLE)) == 3


def test_to_events_reads_name_and_iso_date():
    event = cal.to_events(SAMPLE)[0]
    assert event.name == "Diwali/Deepavali"
    assert event.event_date == date(2026, 11, 8)


def test_to_events_records_the_source():
    assert cal.to_events(SAMPLE)[0].source == "calendarific"


def test_to_events_skips_entries_missing_a_date():
    broken = payload({"name": "No date", "date": {}})
    assert cal.to_events(broken) == []


def test_to_events_skips_entries_missing_a_name():
    broken = payload({"date": {"iso": "2026-01-01"}})
    assert cal.to_events(broken) == []


def test_one_bad_entry_does_not_lose_the_good_ones():
    mixed = payload(holiday(), {"name": "broken", "date": {}})
    assert len(cal.to_events(mixed)) == 1


def test_to_events_tolerates_a_timestamp_date():
    stamped = payload(holiday(iso="2026-11-08T00:00:00+05:30"))
    assert cal.to_events(stamped)[0].event_date == date(2026, 11, 8)


def test_to_events_handles_an_empty_payload():
    assert cal.to_events({}) == [] and cal.to_events(None) == []


# --- type mapping ---------------------------------------------------------

def test_public_holiday_status_outranks_religion():
    # Diwali is tagged both "Gazetted Holiday" and "Hinduism"; the whole country
    # being off work is the stronger demand signal.
    assert cal.to_events(SAMPLE)[0].event_type is EventType.NATIONAL


def test_restricted_holiday_maps_to_observance():
    # The largest bucket in the real data (33 of 71) - must not fall through.
    assert cal.to_events(SAMPLE)[1].event_type is EventType.OBSERVANCE


def test_season_maps_to_seasonal():
    assert cal.to_events(SAMPLE)[2].event_type is EventType.SEASONAL


@pytest.mark.parametrize("token", ["Hinduism", "Christian", "Muslim", "Sikh", "Jain"])
def test_named_religions_map_to_religious(token):
    # Calendarific never writes "religious"; it names the religion directly.
    data = payload(holiday(primary=token, types=(token,)))
    assert cal.to_events(data)[0].event_type is EventType.RELIGIOUS


def test_unknown_type_is_left_unset_rather_than_guessed():
    data = payload(holiday(primary="Something New", types=("Unknown",)))
    assert cal.to_events(data)[0].event_type is None


# --- regions --------------------------------------------------------------

def test_all_states_means_pan_india():
    assert cal.to_events(SAMPLE)[0].regions == []


def test_free_tier_reports_regional_festivals_as_nationwide():
    # Documents a real limitation rather than asserting correct behaviour:
    # Onam is Kerala-only but arrives as states="All". Regionality has to come
    # from the research pass, not from this provider.
    onam = cal.to_events(SAMPLE)[1]
    assert onam.regions == [] and onam.is_regional is False


def test_comma_separated_states_are_split():
    data = payload(holiday(states="Kerala, Tamil Nadu"))
    assert cal.to_events(data)[0].regions == ["Kerala", "Tamil Nadu"]


def test_states_as_objects_are_read_by_name():
    data = payload(holiday(states=[{"name": "Kerala"}, {"name": "Assam"}]))
    assert cal.to_events(data)[0].regions == ["Kerala", "Assam"]


def test_missing_states_means_pan_india():
    data = payload(holiday(states=None))
    assert cal.to_events(data)[0].regions == []


# --- upcoming -------------------------------------------------------------

TODAY = date(2026, 9, 13)


def test_upcoming_drops_past_events():
    # Onam (August) has already happened; lead time is the entire point.
    names = [e.name for e in cal.upcoming(cal.to_events(SAMPLE), TODAY)]
    assert "Onam" not in names


def test_upcoming_keeps_future_events():
    names = [e.name for e in cal.upcoming(cal.to_events(SAMPLE), TODAY)]
    assert names == ["September Equinox", "Diwali/Deepavali"]


def test_upcoming_is_sorted_soonest_first():
    events = cal.upcoming(cal.to_events(SAMPLE), TODAY)
    assert [e.event_date for e in events] == sorted(e.event_date for e in events)


def test_upcoming_keeps_an_event_happening_today():
    data = payload(holiday(iso=TODAY.isoformat()))
    assert len(cal.upcoming(cal.to_events(data), TODAY)) == 1


def test_upcoming_respects_the_window():
    # Diwali is 56 days out, the equinox 10.
    events = cal.upcoming(cal.to_events(SAMPLE), TODAY, within_days=30)
    assert [e.name for e in events] == ["September Equinox"]
