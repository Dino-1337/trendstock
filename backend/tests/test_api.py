"""API-level smoke tests via FastAPI's TestClient - no real server, no network.

The DB is isolated per test (monkeypatched onto a tmp_path file) so these tests
never touch the real data/trendstock.db, and so "ready" states (enriched,
signals present) can be constructed deliberately rather than depending on
whatever happens to be on disk.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.catalog import load_products as load_products_mod
from app.enrichment.models import EnrichedProduct
from app.enrichment.product_enricher import save_enriched
from app.events.models import CalendarEvent
from app.profile.builder import catalog_fingerprint
from app.signals.interpreter import save_signal
from app.signals.models import Phase, Signal, SignalType
from app.storage import db as db_module
from app.storage.db import connect, init_db

client = TestClient(app)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point every app.storage.db.get_db() call (used throughout main.py) at a
    throwaway file, so tests can seed exactly the enrichment/signal state they
    need without touching the real database."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(db_module, "DB_PATH", path)
    return path


@pytest.fixture
def uploaded_catalog():
    """Puts a catalog in place the way a real user does — through POST /api/upload —
    rather than assuming one is bundled.

    The upload path writes to a single real file (data/uploads/current_catalog.csv),
    so this fixture backs up whatever was already there and restores it afterwards.
    An earlier version just unlinked the file on teardown, which meant running the
    test suite silently wiped the catalog the developer had uploaded through the UI.
    Tests must never destroy real local data.
    """
    live = load_products_mod.CURRENT_CATALOG_CSV
    backup = live.read_bytes() if live.exists() else None

    csv_bytes = load_products_mod.DEFAULT_CATALOG_CSV.read_bytes()
    response = client.post(
        "/api/upload",
        files={"file": ("shopify_products.csv", csv_bytes, "text/csv")},
    )
    assert response.json()["ok"] is True
    try:
        yield
    finally:
        if backup is None:
            live.unlink(missing_ok=True)
        else:
            live.write_bytes(backup)


@pytest.fixture
def analyzed_catalog(uploaded_catalog, isolated_db):
    """A catalog that has been through both enrichment and signal
    interpretation - the "ready" state /api/catalog, /api/alerts and
    /api/dashboard all key off. Built directly against the DB rather than by
    running the real (network-calling) pipeline.
    """
    products = load_products_mod.load_products()
    fingerprint = catalog_fingerprint(products)
    today = date.today()
    event_date = today + timedelta(days=10)

    conn = connect(isolated_db)
    init_db(conn)

    records = [
        EnrichedProduct(
            product_id=p["product_id"], title=p["title"],
            categories=[p["product_type"]],
            occasions=["festive"] if i < 3 else [],
            audience="unisex",
        )
        for i, p in enumerate(products)
    ]
    save_enriched(conn, fingerprint, records)

    signal = Signal(
        signal_type=SignalType.EVENT, name="Test Festival",
        event_date=event_date, affected_occasions=["festive"],
        affected_categories=[], demand_lift="high", confidence="high",
        lead_time_days=14, reasoning="test fixture", phase=Phase.BULK,
        relevant=True,
    )
    save_signal(conn, signal)
    conn.commit()
    conn.close()

    return products, fingerprint, event_date


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "version": "0.1.0"}


def test_pipeline_status_reports_snapshot_count(tmp_path, monkeypatch):
    from app.store_trend import trend_history

    monkeypatch.setattr(trend_history, "RAW_DATA_DIR", tmp_path / "raw")
    monkeypatch.setattr(trend_history, "PROCESSED_DATA_DIR", tmp_path / "processed")

    response = client.get("/api/pipeline-status")
    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_count"] == 0
    assert body["geo"] == "IN"
    assert "generated_at" in body


# --- /api/catalog ----------------------------------------------------------

def test_catalog_is_empty_until_something_is_uploaded(tmp_path, monkeypatch):
    """No upload means no products — never a fallback to the bundled sample."""
    monkeypatch.setattr(load_products_mod, "CURRENT_CATALOG_CSV", tmp_path / "nothing.csv")
    body = client.get("/api/catalog").json()
    assert body["summary"]["total_products"] == 0
    assert body["products"] == []
    assert body["enriched"] is False


def test_catalog_reports_unanalysed_when_uploaded_but_not_enriched(uploaded_catalog, isolated_db):
    body = client.get("/api/catalog").json()
    assert body["summary"]["total_products"] == 30
    assert body["enriched"] is False
    # Null, not [], distinguishes "not analysed" from "analysed, found nothing".
    assert body["products"][0]["occasions"] is None


def test_catalog_shape_once_analysed(analyzed_catalog):
    response = client.get("/api/catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["enriched"] is True
    assert body["summary"]["total_products"] == 30
    assert len(body["products"]) == 30

    product = body["products"][0]
    for key in ("product_id", "title", "product_type", "vendor", "price",
                "current_stock", "days_stock_remaining", "stock_status",
                "categories", "occasions", "materials", "audience",
                "style_descriptors", "price_tier", "enrichment_source"):
        assert key in product
    assert product["stock_status"] in ("critical", "low", "ok")
    assert product["occasions"] == ["festive"]


def test_catalog_includes_the_store_profile_when_present(analyzed_catalog):
    body = client.get("/api/catalog").json()
    # The fixture doesn't build a profile row, so this just confirms the key
    # is present and null rather than absent or erroring.
    assert "store_profile" in body


# --- /api/catalog/{product_id} ---------------------------------------------

def test_product_detail_404s_for_an_unknown_product(uploaded_catalog, isolated_db):
    response = client.get("/api/catalog/does-not-exist")
    assert response.status_code == 404


def test_product_detail_shape(analyzed_catalog):
    products, _, event_date = analyzed_catalog
    product_id = products[0]["product_id"]

    response = client.get(f"/api/catalog/{product_id}")
    assert response.status_code == 200
    body = response.json()

    assert body["product"]["product_id"] == product_id
    assert body["enrichment"]["occasions"] == ["festive"]
    assert body["projection"]["points"], "stock projection must not be empty"
    assert body["projection"]["points"][0]["day"] == 0


def test_product_detail_matches_the_signal_that_affects_it(analyzed_catalog):
    products, _, event_date = analyzed_catalog
    # products[0..2] were given occasions=["festive"] in the fixture.
    response = client.get(f"/api/catalog/{products[0]['product_id']}")
    body = response.json()
    assert len(body["signals"]) == 1
    assert body["signals"][0]["name"] == "Test Festival"
    assert body["signals"][0]["event_date"] == event_date.isoformat()


def test_product_detail_has_no_signals_for_an_unmatched_product(analyzed_catalog):
    products, _, _ = analyzed_catalog
    # products[3+] were given occasions=[] in the fixture, so nothing matches.
    response = client.get(f"/api/catalog/{products[5]['product_id']}")
    assert response.json()["signals"] == []


def test_product_detail_flags_a_reorder_when_stock_runs_out_before_the_event(analyzed_catalog):
    products, fingerprint, event_date = analyzed_catalog
    product_id = products[0]["product_id"]

    # Force a stockout that lands before the 10-day-out event by driving
    # velocity up relative to whatever stock the fixture happens to have.
    def fake_load_products(*a, **k):
        return [
            {**p, "avg_daily_sales_14d": (p["current_stock"] / 2) or 1.0}
            if p["product_id"] == product_id else p
            for p in products
        ]

    import app.api.main as main_module
    original = main_module.load_products
    main_module.load_products = fake_load_products
    try:
        body = client.get(f"/api/catalog/{product_id}").json()
    finally:
        main_module.load_products = original

    assert body["reorder_alert"] is not None
    assert body["reorder_alert"]["signal_name"] == "Test Festival"


# --- /api/alerts ------------------------------------------------------------

def test_alerts_not_ready_with_no_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(load_products_mod, "CURRENT_CATALOG_CSV", tmp_path / "nothing.csv")
    body = client.get("/api/alerts").json()
    assert body["ready"] is False
    assert "No catalog" in body["reason"]


def test_alerts_not_ready_before_enrichment(uploaded_catalog, isolated_db):
    body = client.get("/api/alerts").json()
    assert body["ready"] is False
    assert "analysed" in body["reason"]


def test_alerts_ready_shape(analyzed_catalog):
    response = client.get("/api/alerts")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["summary"]["total_signals"] == 1
    assert body["summary"]["next_event"] == "Test Festival"
    assert len(body["signals"][0]["matches"]) == 3


def test_alerts_include_stockout_warnings_for_low_cover_matched_products(analyzed_catalog):
    body = client.get("/api/alerts").json()
    # The fixture catalog's synthetic velocity means at least some of the
    # 3 festive-tagged products plausibly have low cover; just check the
    # warnings list is well-formed rather than asserting a specific count.
    for warning in body["warnings"]:
        assert warning["signal_name"] == "Test Festival"
        assert warning["days_stock_remaining"] <= 14


# --- /api/dashboard ----------------------------------------------------------

def test_dashboard_not_ready_before_analysis(uploaded_catalog, isolated_db):
    body = client.get("/api/dashboard").json()
    assert body["ready"] is False
    assert body["top_warnings"] == []


def test_dashboard_shape_once_ready(analyzed_catalog):
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["stats"]["total_products"] == 30
    assert body["stats"]["enriched_products"] == 30
    assert body["stats"]["with_occasions"] == 3
    assert len(body["next_events"]) >= 1
    assert body["next_events"][0]["name"] == "Test Festival"


def test_dashboard_leads_with_a_bounded_number_of_warnings(analyzed_catalog):
    from app.api.main import DASHBOARD_WARNING_LIMIT

    body = client.get("/api/dashboard").json()
    assert len(body["top_warnings"]) <= DASHBOARD_WARNING_LIMIT


# --- upload / preview (unchanged contract) ----------------------------------

def test_upload_missing_columns_returns_400():
    csv_bytes = b"Handle,Title\nfoo,Foo\n"
    response = client.post(
        "/api/upload",
        files={"file": ("products.csv", csv_bytes, "text/csv")},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "Missing required columns"


def test_upload_preview_groups_the_fixture_csv_into_30_products_and_does_not_persist():
    load_products_mod.CURRENT_CATALOG_CSV.unlink(missing_ok=True)
    csv_bytes = load_products_mod.DEFAULT_CATALOG_CSV.read_bytes()

    response = client.post(
        "/api/upload/preview",
        files={"file": ("shopify_products.csv", csv_bytes, "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["products_loaded"] == 30
    assert len(body["products"]) == 30
    for key in ("product_id", "title", "product_type", "vendor", "image_src",
                "variants", "current_stock", "price"):
        assert key in body["products"][0]

    # A preview must not create/overwrite the persisted catalog file.
    assert not load_products_mod.CURRENT_CATALOG_CSV.exists()


def test_upload_preview_missing_columns_returns_400_same_shape_as_real_upload():
    csv_bytes = b"Handle,Title\nfoo,Foo\n"
    response = client.post(
        "/api/upload/preview",
        files={"file": ("products.csv", csv_bytes, "text/csv")},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "Missing required columns"
