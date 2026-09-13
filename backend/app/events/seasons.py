"""Recurring demand periods, as a second source of Type A signals.

A calendar API answers "when is Diwali" but has no concept of "wedding season".
That gap is not cosmetic: spans are the larger demand drivers in Indian retail.
Verified concretely against the fixture catalog - a Kanjivaram saree tagged
`wedding, bridal` with 1.4 days of stock raised NO warning, because every dated
festival in range was tagged `festive` and nothing on the calendar is
`wedding`.

Seasons are turned into the same CalendarEvent shape the calendar produces, so
they flow through the same interpreter, storage and matcher. A span is
represented by its START date, because that is the moment the seller needs to
have stock ready - the lead time the interpreter estimates then counts back
from there.
"""

import json
from datetime import date

from app.events.models import CalendarEvent, EventType
from app.storage.paths import DATA_DIR

SEASONS_PATH = DATA_DIR / "seasons.json"

SOURCE = "curated_seasons"


def _load(path=None):
    path = path or SEASONS_PATH
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_md(value):
    month, day = value.split("-")
    return int(month), int(day)


def _next_occurrence(month, day, today):
    """The next time this MM-DD falls on or after `today`.

    Seasons recur, so a start date already past this year means the one that
    matters is next year's - otherwise wedding season would read as permanently
    expired from December onward.
    """
    try:
        this_year = date(today.year, month, day)
    except ValueError:
        # 02-29 in a non-leap year; 02-28 is the honest neighbour.
        this_year = date(today.year, month, 28)
    if this_year >= today:
        return this_year
    try:
        return date(today.year + 1, month, day)
    except ValueError:
        return date(today.year + 1, month, 28)


def _is_active(start_md, end_md, today):
    """Whether today falls inside the span, handling year wrap.

    Wedding season runs 11-01 to 02-28, so its end month is numerically before
    its start. Comparing naively would make it never active.
    """
    start = (start_md[0], start_md[1])
    end = (end_md[0], end_md[1])
    now = (today.month, today.day)
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end


def load_seasons(today=None, path=None, within_days=None):
    """Seasons as CalendarEvents, dated by their next start.

    A season already underway is included with its CURRENT start date (in the
    past), so `days_until` goes negative and the matcher can still treat it as
    live via is_active - a seller inside wedding season needs it surfaced, not
    hidden as expired.
    """
    today = today or date.today()
    doc = _load(path)

    events = []
    for entry in doc.get("seasons", []):
        name = (entry.get("name") or "").strip()
        if not name or not entry.get("start") or not entry.get("end"):
            continue

        start_md = _parse_md(entry["start"])
        end_md = _parse_md(entry["end"])
        active = _is_active(start_md, end_md, today)

        if active:
            # Anchor an in-progress season to this year's start so the UI can
            # say "started N days ago" rather than "starts in 300 days".
            try:
                event_date = date(today.year, *start_md)
            except ValueError:
                event_date = date(today.year, start_md[0], 28)
            if event_date > today:
                event_date = date(today.year - 1, *start_md)
        else:
            event_date = _next_occurrence(*start_md, today)

        if within_days is not None and not active:
            if (event_date - today).days > within_days:
                continue

        events.append(CalendarEvent(
            name=name,
            event_type=EventType.SEASONAL,
            regions=entry.get("regions") or [],
            event_date=event_date,
            source=SOURCE,
        ))

    return sorted(events, key=lambda e: e.event_date)


def active_seasons(today=None, path=None):
    """Only the seasons currently underway."""
    today = today or date.today()
    doc = _load(path)
    names = {
        (e.get("name") or "").strip()
        for e in doc.get("seasons", [])
        if e.get("start") and e.get("end")
        and _is_active(_parse_md(e["start"]), _parse_md(e["end"]), today)
    }
    return [e for e in load_seasons(today, path) if e.name in names]
