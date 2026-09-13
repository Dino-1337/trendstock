"""Header canonicalization: a newer Shopify admin export must be accepted, and
normalization must never invent, drop, or overwrite real data."""

from app.catalog.canonicalize import (
    canonical_fieldnames,
    canonical_header_map,
    canonicalize_row,
)
from app.catalog.upload import missing_columns

# Headers as they appear in a real Shopify admin "export products" file.
ADMIN_EXPORT_HEADERS = [
    "Title", "URL handle", "Vendor", "Type", "Tags",
    "Price", "Inventory quantity", "Product image URL",
]

CLASSIC_IMPORT_HEADERS = [
    "Handle", "Title", "Type", "Tags", "Vendor",
    "Variant Price", "Variant Inventory Qty", "Image Src",
]


def test_admin_export_headers_satisfy_required_columns():
    assert missing_columns(canonical_fieldnames(ADMIN_EXPORT_HEADERS)) == []


def test_classic_import_headers_still_pass_untouched():
    assert canonical_header_map(CLASSIC_IMPORT_HEADERS) == {}
    assert missing_columns(canonical_fieldnames(CLASSIC_IMPORT_HEADERS)) == []


def test_alias_matching_ignores_case_and_punctuation():
    mapping = canonical_header_map(["url_handle", "INVENTORY QUANTITY", "Price"])
    assert mapping["url_handle"] == "Handle"
    assert mapping["INVENTORY QUANTITY"] == "Variant Inventory Qty"
    assert mapping["Price"] == "Variant Price"


def test_real_column_wins_over_an_alias():
    """A file with both 'Handle' and 'URL handle' must keep the real Handle."""
    mapping = canonical_header_map(["Handle", "URL handle"])
    assert "URL handle" not in mapping

    row = canonicalize_row({"Handle": "real", "URL handle": "alias"}, mapping)
    assert row["Handle"] == "real"


def test_unknown_columns_are_preserved_not_dropped():
    mapping = canonical_header_map(["URL handle", "SEO title", "Barcode"])
    row = canonicalize_row(
        {"URL handle": "h", "SEO title": "s", "Barcode": "b"}, mapping
    )
    assert row["Handle"] == "h"
    assert row["SEO title"] == "s"
    assert row["Barcode"] == "b"


def test_a_genuinely_incomplete_csv_still_fails():
    """Canonicalization must not paper over actually-missing data."""
    missing = missing_columns(canonical_fieldnames(["Title", "Vendor"]))
    assert "Handle" in missing
    assert "Variant Price" in missing
    assert "Variant Inventory Qty" in missing
