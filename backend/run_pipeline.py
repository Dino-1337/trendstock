"""Standalone local pipeline: fetch Google Trends -> onboard the catalog
(store profile + product enrichment) -> interpret upcoming signals -> match ->
report.

Runs independently of the API - `python run_pipeline.py` is enough. The only
network calls are Google's trending-now feed (via trendspyg, rate-limited,
occasionally throws DownloadError - falls back to existing raw snapshots on
disk), Calendarific for festival dates, Exa for event research, and Groq for
enrichment/interpretation - each optional and each degrading to a thinner but
still-honest result on failure (see app/enrichment/pipeline.py and
app/signals/pipeline.py for the specific fallbacks).
"""

import sys
from datetime import date

from app.catalog.load_products import load_products
from app.enrichment.pipeline import run_onboarding
from app.enrichment.product_enricher import load_enriched
from app.fetch_trends.google_trends import fetch_trending_now
from app.profile.builder import catalog_fingerprint
from app.signals.interpreter import load_signals
from app.signals.matcher import match_all, products_at_risk
from app.storage.db import get_db
from app.store_trend.json_store import store_trend_data
from app.store_trend.process_raw_data import process_day


def _use_utf8_stdout():
    # Trend text is frequently Hindi/Bengali/Telugu/etc; the default Windows
    # console codec (cp1252) crashes on it.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def fetch_and_process():
    try:
        trending = fetch_trending_now()
        path = store_trend_data("google_trending_now", trending)
        print(f"Fetched {len(trending)} trending-now entries -> {path}")
    except Exception as exc:
        print(f"[warn] Live fetch failed ({exc}); using existing raw snapshots on disk.")

    for path in process_day():
        print(f"Processed -> {path}")


def print_report(products, summary, matched, warnings):
    print()
    print("=" * 70)
    print("TRENDSTOCK PIPELINE REPORT  (geo=IN)")
    print("=" * 70)

    if not products:
        print("\nNo catalog uploaded yet - nothing to analyse.")
        print()
        return

    print(f"\n{summary['products']} products, {summary['enriched']} enriched "
          f"({summary['with_occasions']} matched to at least one occasion).")
    print(f"Store type: {summary.get('store_type') or 'unknown (no LLM key configured)'}")

    signal_summary = summary.get("signals") or {}
    if signal_summary:
        print(f"\n{signal_summary.get('events', 0)} upcoming events/seasons checked -> "
              f"{signal_summary.get('relevant', 0)} relevant to this store "
              f"({signal_summary.get('actionable', 0)} actionable).")

    relevant = [e for e in matched if e["matches"]]
    if relevant:
        print(f"\n{len(relevant)} signals with matched products:")
        for entry in relevant[:10]:
            signal = entry["signal"]
            when = f"D{entry['days_until']:+d}" if entry["days_until"] is not None else "ongoing"
            print(f"  - {signal.name:<32} {when:<8} "
                  f"lift={signal.demand_lift.value if signal.demand_lift else '-':<6} "
                  f"-> {len(entry['matches'])} products")

    if warnings:
        print(f"\n{len(warnings)} product(s) at risk (low cover + rising demand):")
        for w in warnings[:15]:
            print(f"  - {w['title']:<34} {w['days_stock_remaining']:.1f}d cover "
                  f"<- {w['signal_name']} ({w['demand_lift']})")
    else:
        print("\nNo products currently at risk.")

    print()


def run():
    _use_utf8_stdout()
    fetch_and_process()

    products = load_products()
    if not products:
        print_report(products, {}, [], [])
        return

    with get_db() as conn:
        summary = run_onboarding(conn, products)
        signals = load_signals(conn, only_relevant=True)
        enriched = load_enriched(conn, catalog_fingerprint(products))

        by_id = {p["product_id"]: p for p in products}
        matched = match_all(signals, enriched, today=date.today())
        warnings = products_at_risk(matched, by_id)

    print_report(products, summary, matched, warnings)


if __name__ == "__main__":
    run()
