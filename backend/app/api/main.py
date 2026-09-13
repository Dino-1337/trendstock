"""Local FastAPI server. No AWS - everything reads/writes local files under data/.

Endpoints match docs/api-contract.md exactly. Where real data can't support a
field (momentum before enough snapshots exist, dashboard deltas with no prior
snapshot to diff against), we return null/empty and say so, rather than
fabricate a plausible-looking number.
"""

from datetime import datetime, timezone

from fastapi import FastAPI, File, Request, UploadFile

from app.logging_setup import get_logger
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.catalog.load_products import load_products
from app.catalog.matching import match_trends_to_catalog
from app.catalog.recommend import recommend_action
from app.catalog.stock import stock_status_for
from app.catalog.upload import preview_upload, process_upload
from app.store_trend.trend_history import build_trend_snapshot, daily_classification_counts
from app.tagging.product_tagger import tag_products
from app.tagging.relevance import apply_relevance_gate
from app.tagging.trend_tagger import tag_trends
from app.tagging.vocabulary import get_vocabulary

APP_VERSION = "0.1.0"
GEO = "IN"
# The dashboard copy itself says "needs ~7 days" - keep the threshold in sync with that.
MOMENTUM_MIN_SNAPSHOTS = 7

log = get_logger("api")

app = FastAPI(title="Trendstock API", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    # Ports on this project are deliberately not 8000/5173 (those belong to
    # another project on this machine) - see start.ps1. Frontend runs on
    # 5273; keep this in sync with frontend/vite.config.js's proxy target.
    allow_origins=["http://localhost:5273"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Contract: "never a 500 [without this shape]" - any endpoint may fail, but
    # the frontend should always get JSON it can render an empty state from.
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": str(exc), "detail": None},
    )


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tag_and_gate_trends(trends):
    """Runs every trend through the controlled-vocabulary tagger, then drops
    anything with zero commerce-relevant tags before it reaches matching or
    the API response - see app/tagging/relevance.py. Returns (kept, dropped).
    """
    vocabulary = get_vocabulary()
    tag_results = tag_trends(trends, vocabulary)
    kept, dropped = apply_relevance_gate(trends, tag_results)
    log.info(
        "relevance gate: %d in -> %d kept, %d dropped (%s)",
        len(trends), len(kept), len(dropped),
        ", ".join(d["trend"] for d in dropped[:5]) or "none",
    )
    return kept, dropped


def _tag_products(products):
    """Attaches controlled-vocabulary 'category_tags'/'tag_source' to each
    product in place, derived from the catalog's own fields. Deliberately
    does NOT touch 'tags' - that's the raw CSV Tags column (e.g. ["nike",
    "sneakers"]), a different, pre-existing field the contract already
    promises; category_tags is the new, separate controlled-vocabulary set."""
    vocabulary = get_vocabulary()
    tag_results = tag_products(products, vocabulary)
    for product in products:
        result = tag_results.get(product["product_id"])
        product["category_tags"] = result.tags if result else []
        product["tag_source"] = result.source if result else None
    return products


def _catalog_with_matches():
    """Shared by /api/catalog and /api/dashboard: tagged/gated trends, tagged
    products enriched with stock_status, matched_trends and a recommendation."""
    snapshot = build_trend_snapshot()
    kept_trends, dropped_trends = _tag_and_gate_trends(snapshot["trends"])

    products = load_products()
    _tag_products(products)
    for product in products:
        product["stock_status"] = stock_status_for(product["days_stock_remaining"])

    products, gaps, match_counts = match_trends_to_catalog(kept_trends, products)

    for product in products:
        product["recommendation"] = recommend_action(
            product["matched_trends"], product["stock_status"], product["days_stock_remaining"]
        )

    for gap in gaps:
        trend = next((t for t in kept_trends if t["trend"] == gap["trend"]), None)
        gap["category_tags"] = trend["category_tags"] if trend else []

    return snapshot, kept_trends, dropped_trends, products, gaps, match_counts


@app.get("/api/health")
def health():
    return {"ok": True, "version": APP_VERSION}


@app.get("/api/trends")
def get_trends():
    snapshot = build_trend_snapshot()
    kept_trends, dropped_trends = _tag_and_gate_trends(snapshot["trends"])

    products = load_products()
    _tag_products(products)
    _, _, match_counts = match_trends_to_catalog(kept_trends, products)

    out_trends = [
        {
            "id": t["id"],
            "trend": t["trend"],
            "traffic_min": t["traffic_min"],
            "traffic_label": t["traffic_label"],
            "first_seen": t["first_seen"],
            "classification": t["classification"],
            "momentum_pct": t["momentum_pct"],
            "spike_ratio": t["spike_ratio"],
            "why": t["why"],
            "category_tags": t["category_tags"],
            "tag_source": t["tag_source"],
            "matched_product_count": match_counts.get(t["trend"], 0),
        }
        for t in kept_trends
    ]

    return {
        "generated_at": now_iso(),
        "geo": GEO,
        "snapshot_count": snapshot["snapshot_count"],
        "trends": out_trends,
        "dropped_trends": {
            "count": len(dropped_trends),
            "trends": dropped_trends,
        },
    }


@app.get("/api/catalog")
def get_catalog():
    _, _, _, products, gaps, _ = _catalog_with_matches()

    matched = sum(1 for p in products if p["matched_trends"])
    at_risk = sum(1 for p in products if p["stock_status"] in ("critical", "low"))

    out_products = [
        {
            "product_id": p["product_id"],
            "title": p["title"],
            "product_type": p["product_type"],
            "vendor": p["vendor"],
            "tags": p["tags"],
            "category_tags": p.get("category_tags", []),
            # Which tagger produced category_tags - rule_based / llm_groq /
            # llm_groq+rule_based. Exposed because a silent fallback to
            # rule-based is otherwise indistinguishable from a working LLM.
            "tag_source": p.get("tag_source"),
            "image_src": p.get("image_src", ""),
            "price": p["price"],
            "current_stock": p["current_stock"],
            "variants": p["variants"],
            "avg_daily_sales_14d": p["avg_daily_sales_14d"],
            "days_stock_remaining": p["days_stock_remaining"],
            "stock_status": p["stock_status"],
            "matched_trends": p["matched_trends"],
            "recommendation": p["recommendation"],
        }
        for p in products
    ]

    return {
        "generated_at": now_iso(),
        "summary": {
            "total_products": len(products),
            "matched": matched,
            "gaps": len(gaps),
            "at_risk": at_risk,
        },
        "products": out_products,
        "gaps": gaps,
    }


@app.post("/api/upload")
async def upload_catalog(file: UploadFile = File(...)):
    raw_bytes = await file.read()
    ok, payload = process_upload(raw_bytes, file.filename)
    if not ok:
        log.warning("upload rejected (%s): %s", file.filename, payload.get("detail") or payload.get("error"))
        return JSONResponse(status_code=400, content=payload)
    log.info(
        "upload accepted (%s): %d products from %d variant rows",
        file.filename, payload["products_loaded"], payload["variants"],
    )
    return payload


@app.post("/api/upload/preview")
async def preview_upload_catalog(file: UploadFile = File(...)):
    """Dry run: same validation/parsing/grouping as POST /api/upload, but
    persists nothing. Lets the frontend show a review step before the seller
    commits the import."""
    raw_bytes = await file.read()
    ok, payload = preview_upload(raw_bytes, file.filename)
    if not ok:
        return JSONResponse(status_code=400, content=payload)
    return payload


@app.post("/api/catalog/retag")
def retag_catalog():
    """Clear the product tag cache and tag again from scratch.

    Tagging is cached, and the cache is what makes repeat requests free — but
    it also means a run that fell back to rule-based (Groq rate-limited, say)
    stays that way until something invalidates it. This is the manual "try the
    LLM again" button, so a seller isn't stuck with a degraded result.
    """
    from app.tagging.cache import CACHE_DIR, TagCache

    TagCache("products", get_vocabulary().version, cache_dir=CACHE_DIR).clear()
    log.info("retag requested: product tag cache cleared")

    products = load_products()
    if not products:
        return {"ok": True, "products_tagged": 0, "untagged": 0, "sources": {}, "message": "No catalog uploaded yet."}

    _tag_products(products)
    sources = {}
    for p in products:
        key = p.get("tag_source") or "none"
        sources[key] = sources.get(key, 0) + 1
    untagged = sum(1 for p in products if not p.get("category_tags"))

    log.info("retag complete: %d products, sources=%s, untagged=%d", len(products), sources, untagged)
    return {
        "ok": True,
        "products_tagged": len(products) - untagged,
        "untagged": untagged,
        "sources": sources,
    }


@app.get("/api/dashboard")
def get_dashboard():
    snapshot, kept_trends, dropped_trends, products, gaps, match_counts = _catalog_with_matches()
    trends = kept_trends

    stats = [
        {
            "key": "trends_tracked", "label": "Trends Tracked",
            "value": len(trends), "delta_pct": None, "direction": None,
        },
        {
            "key": "rising_trends", "label": "Rising Trends",
            "value": sum(1 for t in trends if t["classification"] in ("rising", "spiking")),
            "delta_pct": None, "direction": None,
        },
        {
            "key": "catalog_matches", "label": "Catalog Matches",
            "value": sum(1 for p in products if p["matched_trends"]),
            "delta_pct": None, "direction": None,
        },
        {
            "key": "stock_alerts", "label": "Stock Alerts",
            "value": sum(1 for p in products if p["stock_status"] in ("critical", "low")),
            "delta_pct": None, "direction": None,
        },
    ]
    # delta_pct/direction are null across the board: we persist raw trend
    # snapshots day over day, but not a history of *this aggregate* itself, so
    # there is nothing yet to diff today's stats against. Wiring that up is a
    # small addition (store one summary per day) - not done here since v1 has
    # at most a handful of days of data to diff against anyway.

    points = daily_classification_counts()
    available = snapshot["snapshot_count"] >= MOMENTUM_MIN_SNAPSHOTS
    momentum_chart = {
        "available": available,
        "message": None if available else (
            f"Momentum needs ~{MOMENTUM_MIN_SNAPSHOTS} days of snapshots. "
            f"Collected {snapshot['snapshot_count']} so far."
        ),
        "points": points,
    }

    top_trends = [
        {
            "id": t["id"],
            "trend": t["trend"],
            "traffic_min": t["traffic_min"],
            "classification": t["classification"],
            "matched_product_count": match_counts.get(t["trend"], 0),
        }
        for t in trends[:5]
    ]

    at_risk_products = [
        {
            "product_id": p["product_id"],
            "title": p["title"],
            "days_stock_remaining": p["days_stock_remaining"],
            "stock_status": p["stock_status"],
        }
        for p in sorted(products, key=lambda p: p["days_stock_remaining"])
        if p["stock_status"] in ("critical", "low")
    ][:10]

    return {
        "generated_at": now_iso(),
        "geo": GEO,
        "stats": stats,
        "momentum_chart": momentum_chart,
        "top_trends": top_trends,
        "at_risk_products": at_risk_products,
        "dropped_trends_count": len(dropped_trends),
    }
