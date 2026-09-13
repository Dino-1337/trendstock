"""Exa search client for the Phase 2 (event-refresh) research pass.

Raw ``requests`` rather than the ``exa-py`` SDK, for the same reason
app/tagging/llm_groq.py talks to Groq over plain HTTP: the caching layer stores
JSON, and the SDK would hand back objects that have to be converted back into
dicts to be cached - adding a pinned dependency to do work we then undo.

Request/response contract verified against
https://exa.ai/docs/reference/search-api-guide-for-coding-agents:
  POST https://api.exa.ai/search
  Authorization: Bearer <key>
  body is camelCase; `highlights` is nested under `contents`, NOT top-level
  (top-level is the /contents endpoint's convention - the two are easy to mix
  up and the API rejects the wrong one).

Deliberately unused deprecated parameters, listed so they do not get
reintroduced: useAutoprompt, includeUrls/excludeUrls, livecrawl:"always"
(superseded by contents.maxAgeHours), numSentences, highlightsPerUrl, tokensNum.
"""

from datetime import datetime, timezone

import requests

from app.config import exa_api_key
from app.events.models import Evidence, EvidenceKind
from app.storage import api_cache

API_URL = "https://api.exa.ai/search"
PROVIDER = "exa"
REQUEST_TIMEOUT = 30

DEFAULT_NUM_RESULTS = 10

# "auto" balances relevance and latency and is the documented default. The deep
# variants cost 4-40s per call, which is not worth it for the kind of question
# this agent asks ("which categories spike for Diwali").
DEFAULT_SEARCH_TYPE = "auto"

# Highlights rather than full text: query-relevant excerpts keep token usage
# predictable when the result is fed straight into a model. Full `text` with no
# cap is the documented way to blow up a context window.
DEFAULT_CONTENTS = {"highlights": True}

# Festival-demand research is not breaking news; a week-old answer about which
# categories spike for Diwali is as good as a fresh one. This is what keeps
# repeated development runs off the 20k/month free tier.
DEFAULT_TTL_SECONDS = 7 * 24 * 3600


class ExaError(RuntimeError):
    pass


def is_available():
    return bool(exa_api_key())


def build_request(query, num_results=DEFAULT_NUM_RESULTS, search_type=DEFAULT_SEARCH_TYPE,
                  contents=None, include_domains=None, exclude_domains=None):
    """Build the request body.

    Kept separate from the call so the exact same dict is what gets hashed for
    the cache key - if the body were built inside the request, a parameter
    change could silently miss the cache or, worse, hit a stale entry.
    """
    body = {
        "query": query,
        "type": search_type,
        "numResults": num_results,
        "contents": dict(contents or DEFAULT_CONTENTS),
    }
    if include_domains:
        body["includeDomains"] = list(include_domains)
    if exclude_domains:
        body["excludeDomains"] = list(exclude_domains)
    return body


def _post(body, api_key):
    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def search(query, conn=None, ttl_seconds=DEFAULT_TTL_SECONDS, **kwargs):
    """Run a search, using the cache when a connection is supplied.

    Returns (response, cache_key, was_cached). The cache key is returned so the
    caller can record it on whatever conclusion this search supports - that
    link is what lets the stored reasoning be traced back to the exact response
    that produced it.

    Without `conn` this calls the API every time; that path exists for tests
    and one-off probes, not for the pipeline.
    """
    api_key = exa_api_key()
    if not api_key:
        raise ExaError("EXA_API_KEY is not set")

    body = build_request(query, **kwargs)

    if conn is None:
        return _post(body, api_key), None, False

    return api_cache.get_or_fetch(
        conn, PROVIDER, body, lambda: _post(body, api_key), ttl_seconds=ttl_seconds
    )


def to_evidence(response, cache_key=None, retrieved_at=None, limit=None):
    """Turn a search response into provenance rows.

    Only what is needed to show a human why a conclusion was reached: the
    source, its title, and the excerpt that was actually read. The full
    response stays in api_cache under `cache_key` if more is ever needed.
    """
    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    results = (response or {}).get("results") or []
    if limit is not None:
        results = results[:limit]

    evidence = []
    for result in results:
        highlights = result.get("highlights") or []
        evidence.append(
            Evidence(
                kind=EvidenceKind.SEARCH_RESULT,
                url=result.get("url"),
                title=result.get("title"),
                # Highlights come back as a list of excerpts; join rather than
                # keep only the first, since relevance is spread across them.
                snippet="\n".join(h for h in highlights if h) or None,
                retrieved_at=retrieved_at,
                cache_key=cache_key,
            )
        )
    return evidence
