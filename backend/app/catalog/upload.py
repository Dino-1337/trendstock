"""CSV upload validation + persistence for POST /api/upload.

Required columns match a standard Shopify product export. We deliberately do
not require a sales-history column - Shopify's export never has one (see
load_products.py) - but we warn about it so the seller knows
avg_daily_sales_14d in the response is synthetic, not real.
"""

import csv
import io

from app.catalog.canonicalize import canonical_fieldnames
from app.catalog.load_products import (
    CURRENT_CATALOG_CSV,
    UPLOADS_DIR,
    load_products,
    parse_products_from_text,
)

REQUIRED_COLUMNS = [
    "Handle",
    "Title",
    "Type",
    "Tags",
    "Vendor",
    "Variant Price",
    "Variant Inventory Qty",
]

# Column names that would indicate real sales history is present. None of
# these exist in a standard Shopify product export - this is here so a seller
# who *does* have one (e.g. from a custom export) gets credit for it instead
# of an always-on synthetic-data warning.
SALES_HISTORY_COLUMNS = {
    "units_sold_last_14_days",
    "sales_last_14_days",
    "avg_daily_sales_14d",
    "avg_daily_sales_last_14_days",
}


def missing_columns(headers):
    present = set(headers or [])
    return [col for col in REQUIRED_COLUMNS if col not in present]


def _validate_upload(raw_bytes, filename):
    """Shared by process_upload and preview_upload: decode + required-column
    check. This is the ONE place that decides whether a CSV is acceptable, so
    a preview can never accept something the real import would reject (or
    vice versa).

    Returns (ok, text_or_error_payload, warnings). On failure, the second
    element is already the full {"ok": False, "error", "detail"} body: return
    it straight through.
    """
    if not filename or not filename.lower().endswith(".csv"):
        return False, {"ok": False, "error": "File must be a CSV", "detail": None}, None

    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False, {"ok": False, "error": "File must be a CSV", "detail": None}, None

    reader = csv.DictReader(io.StringIO(text))
    # Normalize recognised header aliases BEFORE checking what's missing, so a
    # newer Shopify admin export ("URL handle", "Price", "Inventory quantity")
    # is accepted rather than rejected for columns it plainly has under other
    # names. See canonicalize.py.
    headers = canonical_fieldnames(reader.fieldnames)
    missing = missing_columns(headers)
    if missing:
        return False, {"ok": False, "error": "Missing required columns", "detail": missing}, None

    warnings = []
    if not (set(headers) & SALES_HISTORY_COLUMNS):
        warnings.append("No sales history column found - daily sales velocity is synthetic.")

    return True, text, warnings


def process_upload(raw_bytes, filename):
    """Validate + (if valid) persist an uploaded CSV.

    Returns (ok, payload) where payload is either the success body
    ({"ok": True, "products_loaded", "variants", "warnings"}) or the failure
    body ({"ok": False, "error", "detail"}) per the API contract.
    """
    ok, text_or_payload, warnings = _validate_upload(raw_bytes, filename)
    if not ok:
        return False, text_or_payload
    text = text_or_payload

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    CURRENT_CATALOG_CSV.write_text(text, encoding="utf-8")

    products = load_products(CURRENT_CATALOG_CSV)
    variants = sum(p["variants"] for p in products)

    return True, {
        "ok": True,
        "products_loaded": len(products),
        "variants": variants,
        "warnings": warnings,
    }


def preview_upload(raw_bytes, filename):
    """Dry run for POST /api/upload/preview: identical validation and
    variant-grouping as process_upload, but persists nothing to
    data/uploads/ — current_catalog.csv is never touched. Lets a seller
    review what an import will actually produce (grouped products, counts,
    warnings) and catch a bad CSV before committing.

    Returns (ok, payload). On failure, payload is the same {"ok": False,
    "error", "detail"} shape as process_upload's failure body. On success,
    payload additionally carries "products": a per-product summary (grouped
    by Handle, one entry per product - not one per CSV row) so the frontend
    can render an accurate preview.
    """
    ok, text_or_payload, warnings = _validate_upload(raw_bytes, filename)
    if not ok:
        return False, text_or_payload
    text = text_or_payload

    products = parse_products_from_text(text)
    variants = sum(p["variants"] for p in products)

    return True, {
        "ok": True,
        "products_loaded": len(products),
        "variants": variants,
        "warnings": warnings,
        "products": [
            {
                "product_id": p["product_id"],
                "title": p["title"],
                "product_type": p["product_type"],
                "vendor": p["vendor"],
                "image_src": p.get("image_src", ""),
                "variants": p["variants"],
                "current_stock": p["current_stock"],
                "price": p["price"],
            }
            for p in products
        ],
    }
