"""Local FastAPI server. No AWS - everything reads/writes local files under data/.

Where real data can't support a field (a forecast before enough snapshots
exist, dashboard deltas with no prior snapshot to diff against), we return
null/empty and say so, rather than fabricate a plausible-looking number.
"""

from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI, File, Request, UploadFile

from app.logging_setup import get_logger
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import jobs
from app.catalog.load_products import load_products
from app.catalog.stock import project_stock, stock_status_for
from app.catalog.upload import preview_upload, process_upload
from app.enrichment.pipeline import run_onboarding
from app.enrichment.product_enricher import load_enriched
from app.profile.builder import catalog_fingerprint, load_profile
from app.signals.interpreter import load_signals
from app.signals.matcher import match_all, products_at_risk
from app.storage.db import get_db
from app.store_trend.trend_history import build_trend_snapshot

APP_VERSION = "0.1.0"
GEO = "IN"

# How many of the highest-urgency warnings the Dashboard leads with. The full
# list lives on /api/alerts - the home screen's job is "what do I act on this
# week", not a duplicate of the detail page.
DASHBOARD_WARNING_LIMIT = 5

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


def _load_signal_state(products, today):
    """Shared by /api/alerts and /api/dashboard: enrichment + signals for the
    live catalog, matched against each other, plus a `ready`/`reason` pair so
    both endpoints can render the same honest "nothing to show yet" states
    instead of two slightly different ones.
    """
    if not products:
        return {"ready": False, "reason": "No catalog uploaded yet."}

    fingerprint = catalog_fingerprint(products)
    with get_db() as conn:
        enriched = load_enriched(conn, fingerprint)
        signals = load_signals(conn, only_relevant=True)

    if not enriched:
        return {"ready": False, "reason": "Catalog has not been analysed yet."}
    if not signals:
        return {"ready": False, "reason": "No upcoming events have been interpreted yet."}

    by_id = {p["product_id"]: p for p in products}
    matched = match_all(signals, enriched, today=today)
    warnings = products_at_risk(matched, by_id)

    return {
        "ready": True, "reason": None, "fingerprint": fingerprint,
        "enriched": enriched, "signals": signals, "matched": matched,
        "warnings": warnings, "by_id": by_id,
    }


def _signal_out(signal, entry, matches_limit=8):
    return {
        "id": signal.id,
        "name": signal.name,
        "signal_type": signal.signal_type.value,
        "source": signal.source,
        "event_date": signal.event_date.isoformat() if signal.event_date else None,
        "days_until": entry["days_until"],
        "in_window": entry["in_window"],
        "lead_time_days": signal.lead_time_days,
        "occasions": signal.affected_occasions,
        "categories": signal.affected_categories,
        "demand_lift": signal.demand_lift.value if signal.demand_lift else None,
        "confidence": signal.confidence.value if signal.confidence else None,
        "reasoning": signal.reasoning,
        "phase": signal.phase.value,
        "matched_count": len(entry["matches"]),
        "matches": entry["matches"][:matches_limit],
        # Provenance: what the refresh pass actually read. Lets the UI show a
        # source rather than asking the seller to trust an assertion.
        "sources": [{"url": e.url, "title": e.title} for e in signal.evidence if e.url],
    }


@app.get("/api/health")
def health():
    return {"ok": True, "version": APP_VERSION}


@app.get("/api/pipeline-status")
def pipeline_status():
    """Raw trend-feed fetch health, shown in the sidebar.

    Deliberately independent of enrichment/signals: this reports how many
    days of Google Trends snapshots have been collected, which is a fact about
    the fetch job regardless of whether a catalog has been uploaded or
    analysed yet.
    """
    snapshot = build_trend_snapshot()
    return {
        "generated_at": now_iso(),
        "geo": GEO,
        "snapshot_count": snapshot["snapshot_count"],
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


@app.post("/api/enrich")
def start_enrichment():
    """Kick off catalog enrichment and return a job id to poll.

    Not synchronous: enrichment is one model call per batch of ten products,
    so a real catalog takes minutes. Holding the request open would time out
    and tell the seller nothing about progress.
    """
    products = load_products()
    if not products:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "No catalog uploaded yet."},
        )

    job_id = jobs.create_job("enrichment", total=len(products))

    def work(progress):
        # A fresh connection: this runs on a worker thread, and SQLite
        # connections must not be shared across threads.
        with get_db() as conn:
            return run_onboarding(conn, products, progress=progress)

    jobs.run_in_background(job_id, work)
    log.info("enrichment job %s started for %d products", job_id, len(products))
    return {"ok": True, **jobs.public_view(jobs.get_job(job_id))}


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "Unknown or expired job."},
        )
    return {"ok": True, **jobs.public_view(job)}


@app.get("/api/catalog")
def get_catalog():
    """The catalog with its AI-derived columns.

    Returns enrichment rows joined onto the live catalog. `enriched` is false
    when nothing has been run yet, so the UI can offer to start it rather than
    showing an empty table that looks broken.
    """
    products = load_products()
    if not products:
        return {
            "generated_at": now_iso(), "enriched": False,
            "summary": {"total_products": 0, "with_occasions": 0},
            "products": [],
        }

    fingerprint = catalog_fingerprint(products)
    with get_db() as conn:
        records = load_enriched(conn, fingerprint)
        profile = load_profile(conn, fingerprint)

    by_id = {r.product_id: r for r in records}
    out = []
    for product in products:
        record = by_id.get(product["product_id"])
        out.append({
            "product_id": product["product_id"],
            "title": product["title"],
            "product_type": product["product_type"],
            "vendor": product["vendor"],
            "image_src": product.get("image_src", ""),
            "price": product["price"],
            "current_stock": product["current_stock"],
            "days_stock_remaining": product["days_stock_remaining"],
            "stock_status": stock_status_for(product["days_stock_remaining"]),
            # AI-derived columns. Null rather than [] when enrichment has not
            # run, so "not analysed yet" stays distinguishable from "analysed,
            # found nothing" - a distinction the old tagger lost.
            "categories": record.categories if record else None,
            "occasions": record.occasions if record else None,
            "materials": record.materials if record else None,
            "audience": record.audience.value if record and record.audience else None,
            "style_descriptors": record.style_descriptors if record else None,
            "price_tier": record.price_tier.value if record and record.price_tier else None,
            "enrichment_source": record.source if record else None,
        })

    return {
        "generated_at": now_iso(),
        "enriched": bool(records),
        "catalog_fingerprint": fingerprint,
        "store_profile": {
            "store_type": profile.inferred.store_type if profile and profile.inferred else None,
            "target_audience": profile.inferred.target_audience if profile and profile.inferred else None,
            "price_positioning": profile.inferred.price_positioning.value if profile and profile.inferred else None,
            "summary": profile.inferred.summary if profile and profile.inferred else None,
        } if profile else None,
        "summary": {
            "total_products": len(products),
            "enriched_products": len(records),
            "with_occasions": sum(1 for r in records if r.has_occasions),
        },
        "products": out,
    }


@app.get("/api/catalog/{product_id}")
def get_product_detail(product_id: str):
    """One product: its enrichment, a stock-depletion projection, and every
    signal that matches it - the per-product view a seller opens to answer
    "when will this likely sell, and am I about to run out beforehand".

    Deliberately not a fabricated sales-prediction curve: there is no real
    order history yet, only synthetic velocity (see
    load_products.synthetic_daily_sales). What IS honest to show is the stock
    trajectory on current velocity, read against the causal signals (events,
    seasons) that are about to raise demand - and whether the stockout date
    falls before or during one of them.
    """
    products = load_products()
    product = next((p for p in products if p["product_id"] == product_id), None)
    if product is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "Unknown product."})

    today = date.today()
    fingerprint = catalog_fingerprint(products)
    with get_db() as conn:
        enriched_list = load_enriched(conn, fingerprint)
        signals = load_signals(conn, only_relevant=True)

    record = next((r for r in enriched_list if r.product_id == product_id), None)

    projection = project_stock(product["current_stock"], product["avg_daily_sales_14d"], today)

    # Reuse the same matcher the catalog-wide view uses, scoped to a product
    # list of one - identical scoring, no separate code path to keep in sync.
    # `matches` is a nested list of one because of that scoping; flattened
    # here since the response is about this product's signals, not products.
    signal_matches = []
    if record is not None and signals:
        matched = match_all(signals, [record], today=today)
        for entry in matched:
            if not entry["matches"]:
                continue
            signal = entry["signal"]
            match = entry["matches"][0]
            lead_window_start = None
            if signal.event_date and signal.lead_time_days is not None:
                lead_window_start = (signal.event_date - timedelta(days=signal.lead_time_days)).isoformat()

            signal_matches.append({
                "name": signal.name,
                "signal_type": signal.signal_type.value,
                "event_date": signal.event_date.isoformat() if signal.event_date else None,
                "days_until": entry["days_until"],
                "in_window": entry["in_window"],
                "lead_time_days": signal.lead_time_days,
                "lead_window_start": lead_window_start,
                "demand_lift": signal.demand_lift.value if signal.demand_lift else None,
                "confidence": signal.confidence.value if signal.confidence else None,
                "reasoning": signal.reasoning,
                "score": match["score"],
                "reasons": match["reasons"],
                "sources": [{"url": e.url, "title": e.title} for e in signal.evidence if e.url],
            })

    # Reorder flag: does the stock run out at or before the nearest matched
    # signal's event date? That is the one comparison this whole view exists
    # to make legible.
    reorder_alert = None
    if projection["stockout_date"] and signal_matches:
        upcoming = [s for s in signal_matches if s["event_date"] and s["event_date"] >= today.isoformat()]
        if upcoming:
            nearest = min(upcoming, key=lambda s: s["event_date"])
            if projection["stockout_date"] <= nearest["event_date"]:
                reorder_alert = {
                    "signal_name": nearest["name"],
                    "event_date": nearest["event_date"],
                    "stockout_date": projection["stockout_date"],
                }

    return {
        "generated_at": now_iso(),
        "product": {
            "product_id": product["product_id"],
            "title": product["title"],
            "product_type": product["product_type"],
            "vendor": product["vendor"],
            "image_src": product.get("image_src", ""),
            "price": product["price"],
            "current_stock": product["current_stock"],
            "variants": product["variants"],
            "avg_daily_sales_14d": product["avg_daily_sales_14d"],
            "days_stock_remaining": product["days_stock_remaining"],
            "stock_status": stock_status_for(product["days_stock_remaining"]),
        },
        "enrichment": {
            "categories": record.categories if record else None,
            "occasions": record.occasions if record else None,
            "materials": record.materials if record else None,
            "audience": record.audience.value if record and record.audience else None,
            "style_descriptors": record.style_descriptors if record else None,
            "price_tier": record.price_tier.value if record and record.price_tier else None,
            "enrichment_source": record.source if record else None,
        } if record else None,
        "projection": projection,
        "signals": signal_matches,
        "reorder_alert": reorder_alert,
    }


@app.get("/api/alerts")
def get_alerts():
    """Upcoming signals, the products each affects, and stockout warnings.

    This is the product's actual deliverable: not "Diwali is coming" but
    "Diwali is coming AND these eight things you sell are about to run out".
    """
    products = load_products()
    today = date.today()
    state = _load_signal_state(products, today)

    if not state["ready"]:
        return {
            "generated_at": now_iso(), "ready": False, "reason": state["reason"],
            "signals": [], "warnings": [], "summary": {},
        }

    out_signals = [_signal_out(e["signal"], e) for e in state["matched"]]

    return {
        "generated_at": now_iso(),
        "ready": True,
        "today": today.isoformat(),
        "signals": out_signals,
        "warnings": state["warnings"],
        "summary": {
            "total_signals": len(out_signals),
            "in_window": sum(1 for s in out_signals if s["in_window"]),
            "warnings": len(state["warnings"]),
            "next_event": out_signals[0]["name"] if out_signals else None,
            "next_event_days": out_signals[0]["days_until"] if out_signals else None,
        },
    }


@app.get("/api/dashboard")
def get_dashboard():
    """Home screen: the smallest number of things worth acting on this week.

    Deliberately not a KPI grid. An operational dashboard's job is to answer
    "what do I do now" in a few seconds - the fuller lists (every signal,
    every product) live on Alerts and Catalog, one click away.
    """
    products = load_products()
    today = date.today()
    state = _load_signal_state(products, today)

    if not state["ready"]:
        return {
            "generated_at": now_iso(), "ready": False, "reason": state["reason"],
            "top_warnings": [], "next_events": [], "stats": {},
        }

    warnings = state["warnings"][:DASHBOARD_WARNING_LIMIT]
    in_window = [e for e in state["matched"] if e["in_window"]]
    upcoming = [e for e in state["matched"] if e["days_until"] is None or e["days_until"] >= 0][:5]

    return {
        "generated_at": now_iso(),
        "ready": True,
        "top_warnings": warnings,
        "next_events": [
            {
                "name": e["signal"].name,
                "signal_type": e["signal"].signal_type.value,
                "days_until": e["days_until"],
                "in_window": e["in_window"],
                "demand_lift": e["signal"].demand_lift.value if e["signal"].demand_lift else None,
                "matched_count": len(e["matches"]),
            }
            for e in upcoming
        ],
        "stats": {
            "total_products": len(products),
            "enriched_products": len(state["enriched"]),
            "with_occasions": sum(1 for r in state["enriched"] if r.has_occasions),
            "signals_in_window": len(in_window),
            "warnings_total": len(state["warnings"]),
        },
    }
