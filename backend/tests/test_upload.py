"""Section E: CSV upload validation. Pure in-memory bytes - no real filesystem
state beyond what process_upload itself persists to data/uploads/, which these
tests clean up after themselves so they don't leak into other test runs."""

import pytest

from app.catalog import upload as upload_module
from app.catalog.load_products import CURRENT_CATALOG_CSV, load_products

VALID_CSV = (
    "Handle,Title,Body (HTML),Vendor,Type,Tags,Published,Option1 Name,Option1 Value,"
    "Variant SKU,Variant Price,Variant Inventory Qty,Variant Requires Shipping,Variant Taxable,Image Src\n"
    "test-hat-0,Test Hat 0,A hat.,Acme,hats,\"acme,hats\",TRUE,Size,One,test-hat-0-1,999,12,TRUE,TRUE,\n"
    "test-hat-0,Test Hat 0,A hat.,Acme,hats,\"acme,hats\",TRUE,Size,Two,test-hat-0-2,999,8,TRUE,TRUE,\n"
)


@pytest.fixture(autouse=True)
def clean_uploaded_catalog():
    had_previous = CURRENT_CATALOG_CSV.exists()
    previous_content = CURRENT_CATALOG_CSV.read_bytes() if had_previous else None
    yield
    if had_previous:
        CURRENT_CATALOG_CSV.write_bytes(previous_content)
    elif CURRENT_CATALOG_CSV.exists():
        CURRENT_CATALOG_CSV.unlink()


def test_valid_csv_is_accepted_and_persisted():
    ok, payload = upload_module.process_upload(VALID_CSV.encode("utf-8"), "products.csv")
    assert ok is True
    assert payload["ok"] is True
    assert payload["products_loaded"] == 1
    assert payload["variants"] == 2
    assert any("synthetic" in w.lower() for w in payload["warnings"])

    # Persisted, so a subsequent load picks it up.
    reloaded = load_products(CURRENT_CATALOG_CSV)
    assert reloaded[0]["title"] == "Test Hat 0"


def test_missing_columns_returns_400_shape_with_missing_list():
    csv_text = "Handle,Title\ntest-hat-0,Test Hat 0\n"
    ok, payload = upload_module.process_upload(csv_text.encode("utf-8"), "products.csv")
    assert ok is False
    assert payload["ok"] is False
    assert payload["error"] == "Missing required columns"
    assert "Variant Inventory Qty" in payload["detail"]
    assert "Type" in payload["detail"]


def test_empty_file_is_reported_as_missing_columns():
    ok, payload = upload_module.process_upload(b"", "products.csv")
    assert ok is False
    assert payload["error"] == "Missing required columns"
    assert set(payload["detail"]) == set(upload_module.REQUIRED_COLUMNS)


def test_non_csv_extension_is_rejected():
    ok, payload = upload_module.process_upload(b"not,a,csv", "products.json")
    assert ok is False
    assert payload["error"] == "File must be a CSV"
    assert payload["detail"] is None


def test_header_only_csv_loads_zero_products():
    header = "Handle,Title,Type,Tags,Vendor,Variant Price,Variant Inventory Qty\n"
    ok, payload = upload_module.process_upload(header.encode("utf-8"), "products.csv")
    assert ok is True
    assert payload["products_loaded"] == 0
    assert payload["variants"] == 0


def test_explicit_sales_history_column_suppresses_warning():
    csv_text = (
        "Handle,Title,Type,Tags,Vendor,Variant Price,Variant Inventory Qty,units_sold_last_14_days\n"
        "test-hat-0,Test Hat 0,hats,\"acme,hats\",Acme,999,12,5\n"
    )
    ok, payload = upload_module.process_upload(csv_text.encode("utf-8"), "products.csv")
    assert ok is True
    assert payload["warnings"] == []


# --- Section E2: preview (dry-run) --------------------------------------


def test_preview_groups_variant_rows_into_products_and_persists_nothing():
    csv_text = (
        "Handle,Title,Type,Tags,Vendor,Variant Price,Variant Inventory Qty,Image Src\n"
        "test-hat-0,Test Hat 0,hats,\"acme,hats\",Acme,999,12,https://example.com/hat.jpg\n"
        "test-hat-0,Test Hat 0,hats,\"acme,hats\",Acme,1099,8,https://example.com/hat.jpg\n"
        "test-shoe-1,Test Shoe 1,shoes,\"acme,shoes\",Acme,2000,5,\n"
    )
    existed_before = CURRENT_CATALOG_CSV.exists()
    content_before = CURRENT_CATALOG_CSV.read_bytes() if existed_before else None

    ok, payload = upload_module.preview_upload(csv_text.encode("utf-8"), "products.csv")

    assert ok is True
    assert payload["ok"] is True
    # 3 variant rows across 2 handles -> 2 products, not 3.
    assert payload["products_loaded"] == 2
    assert payload["variants"] == 3
    assert len(payload["products"]) == 2

    hat = next(p for p in payload["products"] if p["product_id"] == "test-hat-0")
    assert hat["variants"] == 2
    assert hat["current_stock"] == 20  # summed across variants
    assert hat["price"] == 1049.0  # averaged across variants
    assert hat["image_src"] == "https://example.com/hat.jpg"

    shoe = next(p for p in payload["products"] if p["product_id"] == "test-shoe-1")
    assert shoe["image_src"] == ""  # blank Image Src -> "", never None/missing

    # A preview must never write to the persisted catalog file.
    assert CURRENT_CATALOG_CSV.exists() == existed_before
    if existed_before:
        assert CURRENT_CATALOG_CSV.read_bytes() == content_before


def test_preview_rejects_missing_columns_with_the_same_400_shape_as_real_upload():
    csv_text = "Handle,Title\ntest-hat-0,Test Hat 0\n"
    ok, payload = upload_module.preview_upload(csv_text.encode("utf-8"), "products.csv")
    assert ok is False
    assert payload["ok"] is False
    assert payload["error"] == "Missing required columns"
    assert "Variant Inventory Qty" in payload["detail"]
    assert "Type" in payload["detail"]


def test_preview_rejects_non_csv_extension_same_as_real_upload():
    ok, payload = upload_module.preview_upload(b"not,a,csv", "products.json")
    assert ok is False
    assert payload["error"] == "File must be a CSV"
    assert payload["detail"] is None
