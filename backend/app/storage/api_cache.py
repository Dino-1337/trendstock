"""TTL'd cache for upstream API responses (Calendarific, Exa).

Separate from app/tagging/cache.py on purpose. That cache keys on content hash
and invalidates wholesale when the vocabulary version changes - correct for
tags, which are only ever as good as the vocabulary that produced them. This
one caches *time-sensitive* upstream data, where the right question is "how old
is too old", and the answer differs per provider: a resolved festival date is
good for months, a search result about this year's demand is stale in days.

The point is to keep the free tiers comfortable (Exa: 20k req/month) and to
make re-runs during development cost nothing.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone


def _utcnow():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def make_key(provider, request):
    """Stable key for a (provider, request) pair.

    sort_keys matters: the same request built with keys in a different order
    must hit the same cache entry, or the cache silently does nothing.
    """
    payload = json.dumps(request, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(f"{provider}:{payload}".encode("utf-8")).hexdigest()
    return digest


def get(conn, provider, request, now=None):
    """Return the cached response, or None if absent or expired.

    Expired rows are left in place rather than deleted - `purge_expired` handles
    cleanup, so a read stays a read and cannot fail on a locked write.
    """
    now = now or _utcnow()
    key = make_key(provider, request)
    row = conn.execute(
        "SELECT response, expires_at FROM api_cache WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] is not None:
        if datetime.fromisoformat(row["expires_at"]) <= now:
            return None
    return json.loads(row["response"])


def set(conn, provider, request, response, ttl_seconds=None, now=None):
    """Store a response. ttl_seconds=None means it never expires.

    Returns the cache key so callers can record it as provenance on whatever
    conclusion the response feeds into.
    """
    now = now or _utcnow()
    key = make_key(provider, request)
    expires_at = None
    if ttl_seconds is not None:
        expires_at = _iso(now + timedelta(seconds=ttl_seconds))
    conn.execute(
        """
        INSERT INTO api_cache (key, provider, request, response, fetched_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (key) DO UPDATE SET
            response   = excluded.response,
            fetched_at = excluded.fetched_at,
            expires_at = excluded.expires_at
        """,
        (
            key,
            provider,
            json.dumps(request, sort_keys=True, ensure_ascii=False, default=str),
            json.dumps(response, ensure_ascii=False, default=str),
            _iso(now),
            expires_at,
        ),
    )
    return key


def get_or_fetch(conn, provider, request, fetcher, ttl_seconds=None, now=None):
    """Cache-aside helper: return the cached response or call `fetcher()`.

    Returns (response, cache_key, was_cached) - callers want the key for
    provenance and the flag for logging how much real API budget a run spent.
    """
    cached = get(conn, provider, request, now=now)
    if cached is not None:
        return cached, make_key(provider, request), True
    response = fetcher()
    key = set(conn, provider, request, response, ttl_seconds=ttl_seconds, now=now)
    return response, key, False


def purge_expired(conn, now=None):
    now = now or _utcnow()
    cur = conn.execute(
        "DELETE FROM api_cache WHERE expires_at IS NOT NULL AND expires_at <= ?",
        (_iso(now),),
    )
    return cur.rowcount
