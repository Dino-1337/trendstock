"""Stock-status classification shared by the catalog API and the standalone pipeline."""


def stock_status_for(days_stock_remaining):
    """critical: < 7 days | low: 7-14 days | ok: > 14 days."""
    if days_stock_remaining is None:
        return "ok"
    if days_stock_remaining < 7:
        return "critical"
    if days_stock_remaining <= 14:
        return "low"
    return "ok"
