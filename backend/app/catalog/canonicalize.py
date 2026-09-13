"""Map real-world CSV headers onto the canonical column names the rest of the
pipeline expects.

Shopify does not have one product CSV format, it has (at least) two, and both
are things a seller can legitimately export:

- the classic *import* format:  Handle, Variant Price, Variant Inventory Qty
- the newer admin *export*:     URL handle, Price, Inventory quantity

Same data, different headers. Rejecting the second one with "Missing required
columns: Handle, Variant Price, Variant Inventory Qty" is technically accurate
and completely useless to a seller looking at a file that plainly has a handle,
a price and a quantity in it.

So: normalize headers first, validate second. Matching is case-insensitive and
ignores punctuation/whitespace differences, because "Inventory Quantity",
"inventory quantity" and "Inventory_Quantity" are all the same column.

Only headers we actually recognise are renamed. Anything unknown is passed
through untouched - this normalizes, it never invents or drops data.
"""

import re

# canonical name -> aliases it may appear under. The canonical name itself is
# always accepted; it does not need repeating in its own alias list.
COLUMN_ALIASES = {
    "Handle": ["url handle", "product handle", "slug"],
    "Title": ["product title", "product name", "name"],
    "Type": ["product type", "custom product type", "product category"],
    "Tags": ["tag", "product tags"],
    "Vendor": ["brand", "supplier", "manufacturer"],
    "Variant Price": ["price", "variant price", "selling price"],
    "Variant Inventory Qty": [
        "inventory quantity",
        "variant inventory quantity",
        "inventory qty",
        "quantity",
        "qty",
        "stock",
        "current stock",
    ],
    "Image Src": [
        "product image url",
        "image url",
        "image",
        "variant image url",
        "image source",
    ],
}


def _normalize(header):
    """Lowercase, collapse any run of non-alphanumerics to a single space.
    'Variant Inventory Qty' / 'inventory_quantity' / 'Inventory  Quantity'
    all reduce to a comparable form."""
    return re.sub(r"[^a-z0-9]+", " ", (header or "").lower()).strip()


# normalized alias -> canonical name. Built once at import.
_ALIAS_LOOKUP = {}
for _canonical, _aliases in COLUMN_ALIASES.items():
    _ALIAS_LOOKUP[_normalize(_canonical)] = _canonical
    for _alias in _aliases:
        _ALIAS_LOOKUP.setdefault(_normalize(_alias), _canonical)


def canonical_header_map(fieldnames):
    """Returns {original_header: canonical_header} for headers we recognise.

    A canonical column already present in the file always wins: if a CSV has
    both 'Handle' and 'URL handle', the real 'Handle' is kept and the alias is
    left alone rather than overwriting it.
    """
    fieldnames = [f for f in (fieldnames or []) if f is not None]
    already_canonical = {f for f in fieldnames if f in COLUMN_ALIASES}

    mapping = {}
    claimed = set(already_canonical)
    for field in fieldnames:
        if field in already_canonical:
            continue
        canonical = _ALIAS_LOOKUP.get(_normalize(field))
        if canonical and canonical not in claimed:
            mapping[field] = canonical
            claimed.add(canonical)
    return mapping


def canonicalize_row(row, header_map):
    if not header_map:
        return row
    out = dict(row)
    for original, canonical in header_map.items():
        if original in out:
            out[canonical] = out[original]
    return out


def canonicalize_reader(reader):
    """Yields rows from a csv.DictReader with recognised headers renamed to
    their canonical form. Unknown columns are preserved as-is."""
    header_map = canonical_header_map(reader.fieldnames)
    for row in reader:
        yield canonicalize_row(row, header_map)


def canonical_fieldnames(fieldnames):
    """The header list as validation should see it: originals, plus the
    canonical name of anything we recognise."""
    header_map = canonical_header_map(fieldnames)
    return list(fieldnames or []) + [c for c in header_map.values()]
