"""Turn raw trend envelopes into decision-grade metrics.

Reads the raw JSON written by the fetchers and computes, per keyword:
- momentum (4-week % change vs the prior 4 weeks)
- spike ratio (latest value vs 12-week baseline median)
- classification: spiking / rising / steady / falling
plus rising queries (with Google's growth labels like "+250%" or "Breakout")
and top regions, so downstream matching can act on cause and geography.
"""

from datetime import date
from statistics import median
import json

from app.storage.paths import PROCESSED_DATA_DIR, RAW_DATA_DIR

SPIKE_RATIO_THRESHOLD = 2.0
MOMENTUM_RISING_PCT = 15.0
MOMENTUM_FALLING_PCT = -15.0


def compute_series_metrics(series):
    """series: list of {date, value, is_partial} points, oldest first."""
    values = [p["value"] for p in series if not p.get("is_partial")]
    if len(values) < 8:
        return None

    latest = values[-1]
    recent_4 = values[-4:]
    prior_4 = values[-8:-4]
    baseline = median(values[-12:]) if len(values) >= 12 else median(values)

    recent_avg = sum(recent_4) / len(recent_4)
    prior_avg = sum(prior_4) / len(prior_4)
    momentum_pct = (
        round((recent_avg - prior_avg) / prior_avg * 100, 1) if prior_avg else None
    )
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
        "latest_value": latest,
        "recent_4w_avg": round(recent_avg, 1),
        "prior_4w_avg": round(prior_avg, 1),
        "baseline_12w_median": baseline,
        "momentum_4w_pct": momentum_pct,
        "spike_ratio": spike_ratio,
        "classification": classification,
    }


def process_keyword_envelopes(envelopes):
    processed = []
    for env in envelopes:
        metrics = compute_series_metrics(env.get("interest_over_time", []))
        related = env.get("related_queries", {})
        regions = env.get("interest_by_region", [])
        processed.append({
            "keyword": env.get("keyword"),
            "geo": env.get("geo"),
            "timeframe": env.get("timeframe"),
            "fetched_at": env.get("fetched_at"),
            "metrics": metrics,
            "rising_queries": [
                {"query": q["query"], "growth": q.get("formatted_value")}
                for q in related.get("rising", [])
            ],
            "top_queries": [
                {"query": q["query"], "relative_volume": q.get("value")}
                for q in related.get("top", [])
            ],
            "top_regions": [
                {"region": r.get("geo_name"), "value": r.get("value")}
                for r in regions[:10]
            ],
        })
    return processed


def process_trending_now(entries):
    return [
        {
            "trend": e.get("trend"),
            "traffic_min": e.get("traffic_min"),
            "traffic_label": e.get("traffic"),
            "published": e.get("published"),
            "why": [
                {"headline": a.get("headline"), "source": a.get("source")}
                for a in e.get("news_articles", [])
            ],
        }
        for e in entries
    ]


def process_day(day=None):
    day = str(day or date.today())
    raw_dir = RAW_DATA_DIR / day
    out_dir = PROCESSED_DATA_DIR / day
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs = []
    envelope_path = raw_dir / "google_trends.json"
    if envelope_path.exists():
        with open(envelope_path, encoding="utf-8") as f:
            processed = process_keyword_envelopes(json.load(f))
        out_path = out_dir / "google_trends.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(processed, f, indent=2, ensure_ascii=False)
        outputs.append(out_path)

    trending_path = raw_dir / "google_trending_now.json"
    if trending_path.exists():
        with open(trending_path, encoding="utf-8") as f:
            processed = process_trending_now(json.load(f))
        out_path = out_dir / "google_trending_now.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(processed, f, indent=2, ensure_ascii=False)
        outputs.append(out_path)

    return outputs


if __name__ == "__main__":
    for path in process_day():
        print(f"Wrote {path}")
