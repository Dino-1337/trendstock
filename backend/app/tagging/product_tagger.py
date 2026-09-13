"""Tags products from the catalog's own fields - type, vendor, tags, title -
mapped into the controlled vocabulary. Nothing here is specific to any one
catalog: a different uploaded CSV produces different tags automatically,
because the text blob is built from whatever fields that CSV's products
actually have, not from hardcoded product names.
"""

from app.tagging.tagger import tag_batch
from app.tagging.vocabulary import get_vocabulary

CACHE_NAMESPACE = "products"


def _product_text(product):
    tags = ", ".join(product.get("tags") or [])
    return (
        f"Title: {product.get('title', '')}. "
        f"Type: {product.get('product_type', '')}. "
        f"Vendor: {product.get('vendor', '')}. "
        f"Tags: {tags}."
    )


def tag_products(products, vocabulary=None):
    """Mutates nothing; returns {product_id: TagResult}."""
    vocabulary = vocabulary or get_vocabulary()
    items = [(p["product_id"], _product_text(p)) for p in products]
    return tag_batch(items, CACHE_NAMESPACE, vocabulary)
