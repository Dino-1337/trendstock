"""Calendarific client - the source of truth for when events actually happen.

Festival dates are fetched, never inferred. Diwali, Eid, Navratri and most of
the Indian festival calendar are lunar or lunisolar and move every year; asking
a model when Diwali falls produces a confident, plausible, frequently wrong
answer. The model's job is to judge which categories an event lifts and by how
much - the calendar's job is to say when.

Budget note: the free tier allows 500 requests/month, far tighter than Exa's
20,000. One request returns an entire country-year, so with the 30-day TTL real
usage is a handful of calls a year. That ratio is why `fetch_year` deliberately
fetches a whole year rather than querying per month or per festival.

Contract verified against https://calendarific.com/api-documentation:
  GET https://calendarific.com/api/v2/holidays?api_key=&country=IN&year=2026
  -> {"meta": {"code": 200}, "response": {"holidays": [...]}}
"""

import requests

from app.config import calendarific_api_key
from app.events.models import CalendarEvent, EventType
from app.storage import api_cache

API_URL = "https://calendarific.com/api/v2/holidays"
PROVIDER = "calendarific"
REQUEST_TIMEOUT = 30

DEFAULT_COUNTRY = "IN"

# Published festival dates for a given year do not change once set, so this
# could be longer still; 30 days is short enough that a correction upstream
# gets picked up within a billing month.
DEFAULT_TTL_SECONDS = 30 * 24 * 3600

# Calendarific's type strings are free text and country-specific. The values
# actually observed for India 2026 (71 holidays) were:
#   primary_type: Restricted Holiday (33), Gazetted Holiday (17),
#                 Observance (13), Season (4), Hinduism (2), Christian (1),
#                 Government Holiday (1)
#   type[]:       Optional holiday (33), Hinduism (20), National holiday (18),
#                 Observance (16), Season (4), Christian (1)
# Note there is no literal "religious" anywhere - the religion is named
# directly - which is why the tokens below are religion names.
#
# Order is priority, not preference: a holiday is usually tagged several ways
# at once (Diwali is both "Gazetted Holiday" and "Hinduism"), and the first
# match wins. Public-holiday status ranks highest because "the whole country is
# off work" is the strongest demand signal available here.
_TYPE_PATTERNS = (
    ("national holiday", EventType.NATIONAL),
    ("gazetted", EventType.NATIONAL),
    ("government holiday", EventType.NATIONAL),
    ("local holiday", EventType.REGIONAL),
    ("state holiday", EventType.REGIONAL),
    ("hinduism", EventType.RELIGIOUS),
    ("christian", EventType.RELIGIOUS),
    ("muslim", EventType.RELIGIOUS),
    ("islam", EventType.RELIGIOUS),
    ("sikh", EventType.RELIGIOUS),
    ("jain", EventType.RELIGIOUS),
    ("buddh", EventType.RELIGIOUS),
    ("jewish", EventType.RELIGIOUS),
    ("judaism", EventType.RELIGIOUS),
    ("parsi", EventType.RELIGIOUS),
    ("zoroastrian", EventType.RELIGIOUS),
    ("religious", EventType.RELIGIOUS),
    ("season", EventType.SEASONAL),
    ("restricted holiday", EventType.OBSERVANCE),
    ("optional holiday", EventType.OBSERVANCE),
    ("observance", EventType.OBSERVANCE),
)


class CalendarificError(RuntimeError):
    pass


# No is_available() here, unlike exa_client: nothing branches on whether the
# calendar is configured. fetch_year raises CalendarificError on a missing key,
# and the caller treats that the same as any other fetch failure.


def build_request(country=DEFAULT_COUNTRY, year=None, location=None, holiday_type=None):
    """Build the request params, minus the API key.

    The key is excluded on purpose: it is part of authentication, not of the
    question being asked, and including it would make rotating the key
    invalidate every cached year for no reason.
    """
    params = {"country": country, "year": year}
    if location:
        params["location"] = location
    if holiday_type:
        params["type"] = holiday_type
    return params


def _get(params, api_key):
    response = requests.get(
        API_URL, params={**params, "api_key": api_key}, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    payload = response.json()

    # Calendarific answers errors with HTTP 200 and a non-200 `meta.code`, so
    # raise_for_status alone would let an auth failure through as an empty
    # holiday list - indistinguishable from "this country has no holidays".
    code = (payload.get("meta") or {}).get("code")
    if code != 200:
        meta = payload.get("meta") or {}
        raise CalendarificError(
            f"Calendarific returned code {code}: "
            f"{meta.get('error_type')} - {meta.get('error_detail')}"
        )
    return payload


def fetch_year(year, conn=None, country=DEFAULT_COUNTRY, ttl_seconds=DEFAULT_TTL_SECONDS,
               **kwargs):
    """Fetch every holiday for a country-year.

    Returns (payload, cache_key, was_cached), matching exa_client.search so
    callers handle provenance the same way regardless of source.
    """
    api_key = calendarific_api_key()
    if not api_key:
        raise CalendarificError("CALENDARIFIC_API_KEY is not set")

    params = build_request(country=country, year=year, **kwargs)

    if conn is None:
        return _get(params, api_key), None, False

    return api_cache.get_or_fetch(
        conn, PROVIDER, params, lambda: _get(params, api_key), ttl_seconds=ttl_seconds
    )


def _parse_event_type(holiday):
    """Map Calendarific's free-text types onto our enum.

    `type` is a list and `primary_type` a string; both are searched because a
    festival is often tagged religious in one and national in the other.
    """
    candidates = [holiday.get("primary_type") or ""]
    candidates.extend(holiday.get("type") or [])
    haystack = " ".join(c.lower() for c in candidates if c)
    for pattern, event_type in _TYPE_PATTERNS:
        if pattern in haystack:
            return event_type
    return None


def _parse_regions(holiday):
    """Extract the states an event applies to.

    KNOWN LIMITATION - this returns [] for every Indian holiday on the free
    tier. Verified live against India 2026: `states` is the string "All" for
    all 71 holidays, including ones that are unambiguously regional (Onam is
    Kerala, Pongal is Tamil Nadu, Bihu is Assam). Passing `location=in-kl` was
    also tested and changed nothing: same 70 holidays, same "All".

    So regionality cannot come from this provider. It has to come from the
    agent's own reasoning and the Exa research pass instead. The parsing below
    is still written defensively because paid tiers and other countries do
    populate the field, and because it is documented as a string but observed
    elsewhere as a list of state objects.
    """
    states = holiday.get("states")
    if states is None or isinstance(states, str) and states.strip().lower() == "all":
        return []
    if isinstance(states, str):
        return [s.strip() for s in states.split(",") if s.strip()]
    if isinstance(states, list):
        regions = []
        for state in states:
            if isinstance(state, dict):
                name = state.get("name") or state.get("abbrev") or state.get("iso")
                if name:
                    regions.append(name)
            elif isinstance(state, str) and state.strip():
                regions.append(state.strip())
        return regions
    return []


def to_events(payload, source=PROVIDER):
    """Turn a Calendarific payload into CalendarEvent models.

    Malformed entries are skipped rather than failing the whole year: one bad
    holiday record should not cost us the other two hundred.
    """
    holidays = ((payload or {}).get("response") or {}).get("holidays") or []
    events = []
    for holiday in holidays:
        iso = ((holiday.get("date") or {}).get("iso")) or None
        name = holiday.get("name")
        if not iso or not name:
            continue
        # Some entries carry a full timestamp or an offset rather than a plain
        # date; CalendarEvent only wants the date part.
        iso_date = iso.split("T")[0]
        try:
            events.append(
                CalendarEvent(
                    name=name,
                    event_type=_parse_event_type(holiday),
                    regions=_parse_regions(holiday),
                    event_date=iso_date,
                    source=source,
                )
            )
        except ValueError:
            continue
    return events


def upcoming(events, today, within_days=None):
    """Events from today onward, soonest first.

    Past events are dropped: the whole point of this signal is lead time, and
    a festival that has already happened cannot be prepared for.
    """
    future = [e for e in events if e.days_until(today) >= 0]
    if within_days is not None:
        future = [e for e in future if e.days_until(today) <= within_days]
    return sorted(future, key=lambda e: e.event_date)
