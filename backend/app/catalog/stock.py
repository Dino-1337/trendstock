"""Stock-status classification shared by the catalog API and the standalone pipeline."""

from datetime import timedelta

DEFAULT_HORIZON_DAYS = 90


def stock_status_for(days_stock_remaining):
    """critical: < 7 days | low: 7-14 days | ok: > 14 days."""
    if days_stock_remaining is None:
        return "ok"
    if days_stock_remaining < 7:
        return "critical"
    if days_stock_remaining <= 14:
        return "low"
    return "ok"


def project_stock(current_stock, avg_daily_sales, today, horizon_days=DEFAULT_HORIZON_DAYS):
    """Day-by-day stock projection for the per-product chart.

    Deliberately linear, not a real forecast model. avg_daily_sales is
    synthetic velocity (see load_products.synthetic_daily_sales) - there is no
    real order history yet, and dressing a made-up input up in a fancier model
    would imply an accuracy the input cannot support. This answers exactly the
    one question the chart needs: on the current trajectory, when does this
    product run out - so it can be read against the signals that are about to
    raise demand.
    """
    points = []
    stockout_date = None

    for day in range(horizon_days + 1):
        stock_at_day = (
            max(0.0, current_stock - avg_daily_sales * day)
            if avg_daily_sales else float(current_stock)
        )
        points.append({
            "date": (today + timedelta(days=day)).isoformat(),
            "day": day,
            "stock": round(stock_at_day, 1),
        })
        if stockout_date is None and stock_at_day <= 0:
            stockout_date = (today + timedelta(days=day)).isoformat()

    return {"points": points, "stockout_date": stockout_date}
