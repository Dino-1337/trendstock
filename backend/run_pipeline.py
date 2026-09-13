"""Standalone local pipeline: fetch -> process -> tag -> filter -> match -> recommend.

Runs independently of the API - `python run_pipeline.py` is enough. The only
network calls are Google's trending-now feed (via trendspyg, rate-limited,
occasionally throws DownloadError - falls back to existing raw snapshots on
disk) and, if GROQ_API_KEY is set, one batched Groq call each for trend
tagging and product tagging (falls back to the deterministic rule-based
tagger on any failure - see app/tagging/tagger.py). Neither failure mode
stops the pipeline from producing a report.
"""

import sys

from app.catalog.load_products import load_products
from app.catalog.matching import match_trends_to_catalog
from app.catalog.recommend import recommend_action
from app.catalog.stock import stock_status_for
from app.fetch_trends.google_trends import fetch_trending_now
from app.store_trend.json_store import store_trend_data
from app.store_trend.process_raw_data import process_day
from app.store_trend.trend_history import build_trend_snapshot
from app.tagging.product_tagger import tag_products
from app.tagging.relevance import apply_relevance_gate
from app.tagging.trend_tagger import tag_trends
from app.tagging.vocabulary import get_vocabulary


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


def build_catalog_report():
    vocabulary = get_vocabulary()

    snapshot = build_trend_snapshot()
    trend_tag_results = tag_trends(snapshot["trends"], vocabulary)
    trends, dropped_trends = apply_relevance_gate(snapshot["trends"], trend_tag_results)

    products = load_products()
    product_tag_results = tag_products(products, vocabulary)
    for product in products:
        result = product_tag_results.get(product["product_id"])
        product["category_tags"] = result.tags if result else []
        product["tag_source"] = result.source if result else None
        product["stock_status"] = stock_status_for(product["days_stock_remaining"])

    products, gaps, match_counts = match_trends_to_catalog(trends, products)

    for product in products:
        product["recommendation"] = recommend_action(
            product["matched_trends"], product["stock_status"], product["days_stock_remaining"]
        )

    trends_by_name = {t["trend"]: t for t in trends}
    for gap in gaps:
        trend = trends_by_name.get(gap["trend"])
        gap["category_tags"] = trend["category_tags"] if trend else []

    return snapshot, trends, dropped_trends, products, gaps, match_counts


def print_report(snapshot, trends, dropped_trends, products, gaps, match_counts):
    print()
    print("=" * 70)
    print(f"TRENDSTOCK PIPELINE REPORT  (geo=IN, snapshot_count={snapshot['snapshot_count']})")
    print("=" * 70)

    print(
        f"\n{len(snapshot['trends'])} trends fetched, "
        f"{len(dropped_trends)} dropped as not commerce-relevant, "
        f"{len(trends)} kept."
    )
    if dropped_trends:
        print("  Dropped (no commerce-relevant tags found):")
        for d in dropped_trends[:10]:
            print(f"    - {d['trend']}")
        if len(dropped_trends) > 10:
            print(f"    ... and {len(dropped_trends) - 10} more")

    if snapshot["snapshot_count"] < 7:
        print(
            f"\n  (momentum/classification is thin - only {snapshot['snapshot_count']} "
            "day(s) of history collected so far; most trends will read as 'new')"
        )

    if trends:
        print(f"\n{len(trends)} commerce-relevant trends this snapshot:")
        for t in sorted(trends, key=lambda t: t["traffic_min"] or 0, reverse=True)[:10]:
            momentum = f"{t['momentum_pct']:+.1f}%" if t["momentum_pct"] is not None else "n/a"
            tags = ", ".join(t["category_tags"]) or "-"
            print(
                f"  - {t['trend']:<30} traffic={t['traffic_label'] or t['traffic_min']:<8} "
                f"[{t['classification']:<8}] momentum={momentum:<8} tags=[{tags}] "
                f"({t['tag_source']}) matched_products={match_counts.get(t['trend'], 0)}"
            )

    matched_products = [p for p in products if p["matched_trends"]]
    print(f"\n{len(matched_products)} products matched to a trend, {len(gaps)} trend(s) unmatched (gaps).")
    print("\nRecommendations (non-'none' only):")
    actionable = [p for p in products if p["recommendation"]["action"] != "none"]
    for p in sorted(actionable, key=lambda p: p["days_stock_remaining"])[:15]:
        rec = p["recommendation"]
        print(f"  - {p['title']:<20} stock_status={p['stock_status']:<9} -> {rec['action']}")
        print(f"      {rec['reason']}")

    if gaps:
        print(f"\nGaps - commerce-relevant trending with no matching product ({len(gaps)}):")
        for g in gaps[:10]:
            print(f"  - {g['trend']} [{g['classification']}] tags={g.get('category_tags')}")

    print()


def run():
    _use_utf8_stdout()
    fetch_and_process()
    snapshot, trends, dropped_trends, products, gaps, match_counts = build_catalog_report()
    print_report(snapshot, trends, dropped_trends, products, gaps, match_counts)


if __name__ == "__main__":
    run()
