"""API-level smoke tests via FastAPI's TestClient - no real server, no network."""

from fastapi.testclient import TestClient

import pytest

from app.api.main import app
from app.catalog import load_products as load_products_mod
from app.store_trend import trend_history

client = TestClient(app)


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


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "version": "0.1.0"}


def test_trends_empty_but_valid_when_no_data_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(trend_history, "RAW_DATA_DIR", tmp_path / "raw")
    monkeypatch.setattr(trend_history, "PROCESSED_DATA_DIR", tmp_path / "processed")

    response = client.get("/api/trends")
    assert response.status_code == 200
    body = response.json()
    assert body["trends"] == []
    assert body["snapshot_count"] == 0
    assert "generated_at" in body


def test_trends_shape_with_real_fixture_data():
    response = client.get("/api/trends")
    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_count"] >= 1
    if body["trends"]:
        trend = body["trends"][0]
        for key in ("id", "trend", "traffic_min", "traffic_label", "first_seen",
                    "classification", "momentum_pct", "spike_ratio", "why",
                    "matched_product_count"):
            assert key in trend


def test_catalog_is_empty_until_something_is_uploaded(tmp_path, monkeypatch):
    """No upload means no products — never a fallback to the bundled sample."""
    monkeypatch.setattr(load_products_mod, "CURRENT_CATALOG_CSV", tmp_path / "nothing.csv")
    body = client.get("/api/catalog").json()
    assert body["summary"]["total_products"] == 0
    assert body["products"] == []


def test_catalog_shape(uploaded_catalog):
    response = client.get("/api/catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_products"] == 30
    assert len(body["products"]) == 30
    product = body["products"][0]
    assert "category_tags" in product
    for key in ("product_id", "title", "product_type", "vendor", "tags", "price",
                "current_stock", "variants", "avg_daily_sales_14d", "image_src",
                "days_stock_remaining", "stock_status", "matched_trends", "recommendation"):
        assert key in product
    assert product["stock_status"] in ("critical", "low", "ok")
    assert body["products"][0]["recommendation"]["action"] in (
        "promote", "increase_stock", "reduce_reorder_risk", "discount", "none",
    )


def test_dashboard_shape():
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert len(body["stats"]) == 4
    assert {s["key"] for s in body["stats"]} == {
        "trends_tracked", "rising_trends", "catalog_matches", "stock_alerts",
    }
    assert "available" in body["momentum_chart"]
    assert "points" in body["momentum_chart"]


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
