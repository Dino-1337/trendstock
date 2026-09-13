"""Signal pipeline: calendar + seasons -> interpretation -> storage.

Runs after onboarding (which produces the store profile and enriched
products), because interpretation is grounded in the profile - "is this
festive?" is a different question for a bridal store than a streetwear one.

Two sources, one shape: Calendarific supplies dated festivals, seasons.json
supplies recurring spans. Both become CalendarEvents and go through the same
interpreter, so downstream code never needs to know which is which.
"""

from datetime import date

from app.events import calendar_client as cal
from app.events import seasons as seasons_source
from app.logging_setup import get_logger
from app.signals import interpreter
from app.signals.models import Phase

log = get_logger("signals.pipeline")

# How far ahead to interpret. Diwali's lead time is ~35 days, so 120 gives
# comfortable margin while keeping the bulk pass to a few batched calls.
DEFAULT_HORIZON_DAYS = 120

STAGES = {
    "calendar": "Fetching the festival calendar",
    "interpreting": "Working out what affects your store",
    "storing": "Saving results",
    "complete": "Done",
}


def _noop(**_fields):
    pass


def collect_events(today, conn=None, horizon_days=DEFAULT_HORIZON_DAYS,
                   include_seasons=True):
    """Upcoming dated festivals plus recurring seasons, soonest first.

    Spans the year boundary when the horizon does: a 120-day window from
    October reaches into February, and fetching only this year's calendar
    would silently lose January and February.
    """
    events = []

    years = {today.year}
    if (today.month, today.day) > (9, 1):
        years.add(today.year + 1)

    for year in sorted(years):
        try:
            payload, _, _ = cal.fetch_year(year, conn=conn)
            events.extend(cal.to_events(payload))
        except Exception as exc:
            log.warning("could not fetch calendar for %s: %s", year, exc)

    upcoming = cal.upcoming(events, today, within_days=horizon_days)

    if include_seasons:
        # Seasons already underway are included with a past start date, so
        # they are added rather than filtered through `upcoming`.
        upcoming = upcoming + seasons_source.load_seasons(
            today, within_days=horizon_days
        )
        upcoming.sort(key=lambda e: e.event_date)

    return upcoming


def run_signal_pass(conn, store_context, today=None, progress=None,
                    horizon_days=DEFAULT_HORIZON_DAYS, phase=Phase.BULK,
                    models=None):
    """Interpret and store every upcoming signal. Returns a summary."""
    progress = progress or _noop
    today = today or date.today()

    progress(stage="calendar", message=STAGES["calendar"])
    events = collect_events(today, conn=conn, horizon_days=horizon_days)

    if not events:
        progress(stage="complete", message="No upcoming events found", total=0)
        return {"events": 0, "interpreted": 0, "relevant": 0, "stored": 0}

    progress(stage="interpreting", message=STAGES["interpreting"],
             progress=0, total=len(events))
    signals = interpreter.interpret_events(
        events, store_context, today, conn=conn, phase=phase,
        models=models, progress=progress,
    )

    progress(stage="storing", message=STAGES["storing"])
    for signal in signals:
        interpreter.save_signal(conn, signal)

    relevant = sum(1 for s in signals if s.relevant)
    actionable = sum(1 for s in signals if s.can_match)

    progress(stage="complete", message=STAGES["complete"], progress=len(events))
    log.info(
        "signal pass: %d events -> %d interpreted, %d relevant, %d actionable",
        len(events), len(signals), relevant, actionable,
    )

    return {
        "events": len(events),
        "interpreted": len(signals),
        "relevant": relevant,
        "actionable": actionable,
        "stored": len(signals),
    }
