"""Load a Shopify product CSV export into normalized product records.

A Shopify export has one row per variant, so rows are grouped by Handle into
one product each. Stock is summed across variants, since restock decisions are
made at product level, not per size.

The export carries no sales history, so avg_daily_sales_14d is generated
synthetically (seeded by handle, so it is stable across runs) until real
order data is connected.
"""

from pathlib import Path
import csv
import io
import random

from app.catalog.canonicalize import canonicalize_reader

from app.storage.paths import DATA_DIR, FIXTURES_DIR, UPLOADS_DIR  # noqa: F401

DEFAULT_CATALOG_CSV = FIXTURES_DIR / "shopify_products.csv"
CURRENT_CATALOG_CSV = UPLOADS_DIR / "current_catalog.csv"

# Kept for backwards compatibility with any existing callers/imports.
CATALOG_CSV = DEFAULT_CATALOG_CSV


def active_catalog_path():
    """The CSV /api/catalog should read: the most recently uploaded one, or None.

    There is deliberately NO fallback to the bundled sample catalog. A seller who
    has not uploaded anything has an empty catalog, and the UI says so — showing
    somebody else's 30 sample products as if they were theirs is exactly the kind
    of fabricated data this project has been stripping out. The sample CSV in
    data/fixtures/ is kept for tests, which pass it explicitly.
    """
    return CURRENT_CATALOG_CSV if CURRENT_CATALOG_CSV.exists() else None


def synthetic_daily_sales(handle):
    """Stable per-product sales velocity, so stockout numbers don't move between runs."""
    return round(random.Random(handle).uniform(0.3, 4.0), 2)


def _group_rows_into_products(reader):
    """Group Shopify CSV rows (one per variant) by Handle into one product
    record per Handle. Shared by load_products() (reads from disk) and
    parse_products_from_text() (in-memory, for the upload preview dry-run) so
    the two never disagree about what an import will actually produce.
    """
    products = {}

    # Recognised header aliases are renamed to canonical names first, so this
    # function only ever deals in "Handle"/"Variant Price"/etc regardless of
    # which Shopify export format the seller uploaded. See canonicalize.py.
    for row in canonicalize_reader(reader):
        handle = row["Handle"]
        product = products.setdefault(handle, {
            "product_id": handle,
            "title": row["Title"],
            "product_type": row["Type"],
            "tags": [t.strip() for t in row["Tags"].split(",") if t.strip()],
            "vendor": row["Vendor"],
            # Shopify repeats the image on every variant row of a handle;
            # take it from the first row only. Missing column -> "".
            "image_src": (row.get("Image Src") or "").strip(),
            "current_stock": 0,
            "variants": 0,
            "prices": [],
        })
        product["current_stock"] += int(row["Variant Inventory Qty"] or 0)
        product["variants"] += 1
        product["prices"].append(float(row["Variant Price"] or 0))

    for product in products.values():
        prices = product.pop("prices")
        product["price"] = round(sum(prices) / len(prices), 2)
        product["avg_daily_sales_14d"] = synthetic_daily_sales(product["product_id"])
        product["days_stock_remaining"] = round(
            product["current_stock"] / product["avg_daily_sales_14d"], 1
        )
        # Everything a trend keyword could reasonably match against.
        product["match_text"] = " ".join(
            [product["title"], product["product_type"], product["vendor"], *product["tags"]]
        ).lower()

    return list(products.values())


def load_products(csv_path=None):
    csv_path = csv_path or active_catalog_path()
    if csv_path is None or not Path(csv_path).exists():
        return []  # nothing uploaded yet

    with open(csv_path, encoding="utf-8") as f:
        return _group_rows_into_products(csv.DictReader(f))


def parse_products_from_text(text):
    """Same grouping as load_products(), but from CSV text already in memory
    and without touching disk at all. Powers the upload preview dry-run —
    one parser, one source of truth, so a preview can never disagree with
    what the real import produces.
    """
    return _group_rows_into_products(csv.DictReader(io.StringIO(text)))


if __name__ == "__main__":
    products = load_products()
    print(f"{len(products)} products loaded\n")
    for p in sorted(products, key=lambda p: p["days_stock_remaining"])[:10]:
        print(
            f"{p['title']:22} stock={p['current_stock']:>3} "
            f"sales/day={p['avg_daily_sales_14d']:>5} "
            f"days_left={p['days_stock_remaining']:>6}"
        )
