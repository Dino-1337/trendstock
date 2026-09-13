"""Google Trends fetching. Two trendspyg code paths matter here and they are
NOT interchangeable:

- RSS (download_google_trends_rss): fast, pure HTTP, no headless Chrome. Has
  news article headlines. Has NO category filtering at all - trendspyg's own
  docstring lists "Category filtering" under RSS's "NOT Provided", full stop.
- CSV (download_google_trends_csv): drives headless Chrome, slower (~8-12s),
  rate-limited like the (disabled) explore/keyword path. DOES support
  `category` filtering (trendspyg.config.CATEGORIES - 20 topic slugs like
  "shopping", "entertainment", "sports"). Has NO headlines at all.

That split is a real constraint, not an oversight: there's no single call
that gets both category filtering and headlines. Since headlines are load-
bearing for trend_tagger.py, RSS stays the primary source; category
membership is fetched separately via CSV and used to narrow the RSS list
down to commerce-relevant categories (see _category_allowed_trend_names).

This is a distinct, separate thing from `category` (numeric id) on the
explore/keyword path below, which stays disabled - do not confuse the two.
"""

from trendspyg import download_google_trends_rss

try:
    from trendspyg import download_google_trends_csv
except ImportError:  # pragma: no cover - trendspyg always ships both today
    download_google_trends_csv = None

from app.storage.paths import TRENDSPYG_DOWNLOAD_DIR
from app.store_trend.json_store import store_trend_data

GEO = "IN"

# trendspyg.config.CATEGORIES has 20 slugs. "shopping" is the obvious
# commerce category; "entertainment" is included because the PRD's own
# scenarios (movie releases, celebrity moments) are entertainment-category
# trends, not shopping-category ones - see PRD section 7.4.
TRENDING_CATEGORIES = ["shopping", "entertainment"]

CSV_DOWNLOAD_DIR = TRENDSPYG_DOWNLOAD_DIR


def _category_allowed_trend_names(geo=GEO, categories=TRENDING_CATEGORIES):
    """Best-effort category membership via the CSV path (RSS has none - see
    module docstring). Returns None (not an empty set) if the CSV path itself
    is unavailable or fails, meaning "couldn't determine categories, don't
    filter on that basis" rather than "nothing is allowed" - a flaky browser
    automation call must never turn into every trend being silently dropped.

    Known limitation, found by live-testing against Google's real Trending
    Now page for geo=IN: category filtering here barely narrows anything.
    "entertainment" came back byte-identical to "all" (251/251 trends,
    identical order) and "shopping" was a near-superset of "all" (255 vs 251,
    with all 251 "all" trends included in "shopping"'s list) rather than a
    narrower one. Google's Trending Now page may simply not enforce `cat=`
    the way the old Daily Trends CSV export used to. This layer is kept
    because it's cheap, self-contained, and may behave better for other
    geos/times - but the real filtering work is done by the relevance gate
    (app/tagging/relevance.py), not by this category param.
    """
    if download_google_trends_csv is None:
        return None
    allowed = set()
    got_any = False
    for category in categories:
        try:
            rows = download_google_trends_csv(
                geo=geo, category=category, output_format="dict",
                download_dir=str(CSV_DOWNLOAD_DIR), max_retries=1, timeout=20,
            )
        except Exception:
            continue
        got_any = True
        for row in rows or []:
            name = (row.get("Trends") or "").strip().lower()
            if name:
                allowed.add(name)
    return allowed if got_any else None


def fetch_trending_now(geo=GEO, filter_categories=True):
    """Real-time spiking searches with traffic volume and the news articles
    explaining the spike (movie release, celebrity moment, event...).

    Needs no keyword input — Google decides what is trending, so this is the
    discovery path. Each call is a snapshot with no history, so momentum has
    to be built by accumulating these snapshots day over day.

    filter_categories=True additionally narrows the RSS list to trends that
    also appear in the CSV path's shopping/entertainment category export (see
    TRENDING_CATEGORIES and _category_allowed_trend_names's docstring for why
    this is currently a weak filter in practice, not a strong one). Set False
    to skip the extra CSV round-trips entirely (faster, no category signal).
    """
    entries = download_google_trends_rss(geo=geo)
    if not filter_categories:
        return entries

    allowed = _category_allowed_trend_names(geo=geo)
    if allowed is None:
        return entries  # couldn't determine category membership - don't drop on that basis

    return [e for e in entries if (e.get("trend") or "").strip().lower() in allowed]


# --- Keyword tracking: disabled ---------------------------------------------
# Parked until seed keywords come from somewhere real (the seller's own catalog
# or the trending feed below) instead of being hardcoded guesses.
#
# from trendspyg import download_google_trends_explore
#
# TRACKED_KEYWORDS = ["fashion trends", "trending products"]
# TIMEFRAME = "today 12-m"
#
# def fetch_keyword_envelopes(keywords=TRACKED_KEYWORDS, geo=GEO):
#     """Full explore envelope per keyword: interest_over_time (weekly series),
#     related_queries (top + rising with growth %), interest_by_region."""
#     envelopes = []
#     for keyword in keywords:
#         env = download_google_trends_explore(
#             keyword,
#             geo=geo,
#             timeframe=TIMEFRAME,
#             max_retries=15,
#             retry_wait=15.0,
#         )
#         envelopes.append(env)
#     return envelopes


if __name__ == "__main__":
    trending = fetch_trending_now()
    path = store_trend_data("google_trending_now", trending)
    print(f"Saved {len(trending)} trending-now entries to {path}")
