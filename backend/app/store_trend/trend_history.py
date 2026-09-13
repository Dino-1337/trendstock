"""Turn accumulated daily raw snapshots into per-trend history.

Google's trending-now feed is a snapshot with no time series of its own — it
only tells us what is trending *today*. History has to be built by us, by
comparing today's `traffic_min` per trend against the same trend's value on
previous days, as those days' raw snapshots pile up in `data/raw/{date}/`.

With only day-over-day points (not the weekly windows `compute_series_metrics`
expects), classification needs at least 2 daily snapshots of a trend to say
anything at all. A trend seen for the first time is honestly reported as
"new" with null momentum, exactly as the API contract requires.
"""

from datetime import datetime, timezone
from statistics import median
import json
import re

from app.storage.paths import PROCESSED_DATA_DIR, RAW_DATA_DIR  # noqa: F401  (re-exported; tests monkeypatch these names here)

RAW_FILENAME = "google_trending_now.json"
PROCESSED_FILENAME = "google_trending_now.json"

# Same thresholds process_raw_data.py uses for the weekly keyword series, reused
# here for day-over-day comparison so "spiking"/"rising"/"falling" mean roughly
# the same thing across both pipelines. Day-over-day is noisier than a rolling
# weekly window, so this is a best-effort call, not a claim of equivalent rigor.
SPIKE_RATIO_THRESHOLD = 2.0
MOMENTUM_RISING_PCT = 15.0
MOMENTUM_FALLING_PCT = -15.0

_SLUG_RE = re.compile(r"[^\w]+", re.UNICODE)


def slugify(text):
    """'The Mummy 4' -> 'the-mummy-4'. Deliberately Unicode-aware (\\w, not
    a-z0-9 only) - most of this feed's trends are Hindi/Bengali/Telugu/etc,
    and stripping non-ASCII would collapse every non-Latin trend to the same
    empty slug, colliding on id."""
    slug = _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")
    return slug or "trend"


def parse_published_to_utc(published):
    """'2026-08-05 02:50:00-07:00' -> '2026-08-05T09:50:00Z'. Returns None if unparseable."""
    if not published:
        return None
    try:
        dt = datetime.fromisoformat(str(published))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_raw_snapshots(raw_dir=None, filename=RAW_FILENAME):
    """{date_str: {slug: {"trend": str, "traffic_min": int|None, "published": str|None}}},
    for every date directory under data/raw that has a trending-now file. Dates are
    plain '%Y-%m-%d' strings and sort lexicographically = chronologically.

    raw_dir defaults to the module-level RAW_DATA_DIR, resolved at call time
    (not bound at def time) so tests can monkeypatch it."""
    raw_dir = raw_dir or RAW_DATA_DIR
    snapshots = {}
    if not raw_dir.exists():
        return snapshots

    for day_dir in sorted(raw_dir.iterdir()):
        if not day_dir.is_dir():
            continue
        file_path = day_dir / filename
        if not file_path.exists():
            continue
        try:
            with open(file_path, encoding="utf-8") as f:
                entries = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(entries, list):
            continue

        by_slug = {}
        for entry in entries:
            trend = entry.get("trend")
            if not trend:
                continue
            slug = slugify(trend)
            by_slug[slug] = {
                "trend": trend,
                "traffic_min": entry.get("traffic_min"),
                "published": entry.get("published"),
            }
        snapshots[day_dir.name] = by_slug

    return snapshots


def classify_series(series):
    """series: ascending list of (date_str, traffic_min) for one trend, the last
    point being 'today'. Needs >= 2 points to say anything about momentum."""
    values = [v for _, v in series if v is not None]
    if len(values) < 2:
        return {"classification": "new", "momentum_pct": None, "spike_ratio": None}

    latest = values[-1]
    prior_val = values[-2]
    momentum_pct = (
        round((latest - prior_val) / prior_val * 100, 1) if prior_val else None
    )
    baseline_vals = values[:-1]
    baseline = median(baseline_vals) if baseline_vals else None
    spike_ratio = round(latest / baseline, 2) if baseline else None

    if spike_ratio is not None and spike_ratio >= SPIKE_RATIO_THRESHOLD:
        classification = "spiking"
    elif momentum_pct is not None and momentum_pct >= MOMENTUM_RISING_PCT:
        classification = "rising"
    elif momentum_pct is not None and momentum_pct <= MOMENTUM_FALLING_PCT:
        classification = "falling"
    else:
        classification = "steady"

    return {
        "classification": classification,
        "momentum_pct": momentum_pct,
        "spike_ratio": spike_ratio,
    }


def _latest_processed_date(processed_dir=None, filename=PROCESSED_FILENAME):
    processed_dir = processed_dir or PROCESSED_DATA_DIR
    if not processed_dir.exists():
        return None
    candidates = sorted(
        (d.name for d in processed_dir.iterdir() if d.is_dir() and (d / filename).exists()),
        reverse=True,
    )
    return candidates[0] if candidates else None


def build_trend_snapshot(processed_dir=None, raw_dir=None):
    """The full picture for GET /api/trends: today's ranked list enriched with
    classification/momentum/first_seen derived from accumulated raw snapshots.

    Returns {"trends": [...], "snapshot_count": int, "dates": [...], "latest_date": str|None}.
    Returns an empty-but-valid shape (never raises) when no data exists at all.
    """
    processed_dir = processed_dir or PROCESSED_DATA_DIR
    raw_dir = raw_dir or RAW_DATA_DIR
    raw_snapshots = load_raw_snapshots(raw_dir)
    dates = sorted(raw_snapshots.keys())
    snapshot_count = len(dates)

    latest_date = _latest_processed_date(processed_dir)
    if latest_date is None:
        return {"trends": [], "snapshot_count": snapshot_count, "dates": dates, "latest_date": None}

    processed_path = processed_dir / latest_date / PROCESSED_FILENAME
    try:
        with open(processed_path, encoding="utf-8") as f:
            today_entries = json.load(f)
    except (OSError, json.JSONDecodeError):
        today_entries = []

    trends = []
    for entry in today_entries:
        trend_text = entry.get("trend")
        if not trend_text:
            continue
        slug = slugify(trend_text)

        series = [
            (d, raw_snapshots[d][slug]["traffic_min"])
            for d in dates
            if slug in raw_snapshots.get(d, {})
        ]
        metrics = classify_series(series) if series else {
            "classification": "new", "momentum_pct": None, "spike_ratio": None,
        }

        first_seen_published = None
        for d in dates:
            if slug in raw_snapshots.get(d, {}):
                first_seen_published = raw_snapshots[d][slug].get("published")
                break

        trends.append({
            "id": f"{slug}-{latest_date}",
            "slug": slug,
            "trend": trend_text,
            "traffic_min": entry.get("traffic_min"),
            "traffic_label": entry.get("traffic_label"),
            "first_seen": parse_published_to_utc(first_seen_published) or parse_published_to_utc(entry.get("published")),
            "classification": metrics["classification"],
            "momentum_pct": metrics["momentum_pct"],
            "spike_ratio": metrics["spike_ratio"],
            "why": entry.get("why", []),
        })

    trends.sort(key=lambda t: t["traffic_min"] or 0, reverse=True)

    return {
        "trends": trends,
        "snapshot_count": snapshot_count,
        "dates": dates,
        "latest_date": latest_date,
    }


def daily_classification_counts(raw_dir=None):
    """For the dashboard momentum chart: one point per day already collected,
    counting how many trends active that day were spiking/rising/steady, using
    only data available up to and including that day (never peeking ahead)."""
    raw_dir = raw_dir or RAW_DATA_DIR
    raw_snapshots = load_raw_snapshots(raw_dir)
    dates = sorted(raw_snapshots.keys())

    series_by_slug = {}
    points = []
    for d in dates:
        counts = {"spiking": 0, "rising": 0, "steady": 0}
        for slug, info in raw_snapshots[d].items():
            series = series_by_slug.setdefault(slug, [])
            series.append((d, info["traffic_min"]))
            classification = classify_series(series)["classification"]
            if classification in counts:
                counts[classification] += 1
        points.append({"date": d, **counts})

    return points
