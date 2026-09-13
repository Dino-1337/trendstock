"""Exa client tests. Every HTTP call is stubbed - the suite must never spend
real API budget, and the free tier is the reason the cache exists at all.

The canned response mirrors the shape verified live against
https://exa.ai/docs/reference/search-api-guide-for-coding-agents.
"""

from datetime import datetime, timezone

import pytest

from app.events.models import EvidenceKind
from app.research import exa_client
from app.storage import db

SAMPLE_RESPONSE = {
    "requestId": "abc",
    "resolvedSearchType": "neural",
    "results": [
        {
            "title": "Diwali Saree Demand 2026",
            "url": "https://example.com/diwali-saree",
            "publishedDate": "2026-08-01T00:00:00.000Z",
            "highlights": ["Saree demand peaks 2 weeks before Diwali."],
        },
        {
            "title": "Surat Textile Market Growth",
            "url": "https://example.com/surat",
            "highlights": ["Festival season lifts orders.", "Second excerpt."],
        },
    ],
    "costDollars": {"total": 0.007},
}


@pytest.fixture
def conn(tmp_path):
    connection = db.init_db(db.connect(tmp_path / "t.db"))
    yield connection
    connection.close()


@pytest.fixture
def fake_key(monkeypatch):
    monkeypatch.setattr(exa_client, "exa_api_key", lambda: "test-key")


@pytest.fixture
def spy(monkeypatch, fake_key):
    """Record every outbound call so tests can assert on cache behaviour."""
    calls = []

    def _post(body, api_key):
        calls.append((body, api_key))
        return SAMPLE_RESPONSE

    monkeypatch.setattr(exa_client, "_post", _post)
    return calls


# --- request building -----------------------------------------------------

def test_request_uses_documented_defaults():
    body = exa_client.build_request("diwali")
    assert body["query"] == "diwali"
    assert body["type"] == "auto"
    assert body["numResults"] == exa_client.DEFAULT_NUM_RESULTS


def test_highlights_are_nested_under_contents():
    # Top-level `highlights` is the /contents convention; /search rejects it.
    body = exa_client.build_request("diwali")
    assert body["contents"] == {"highlights": True}
    assert "highlights" not in body


def test_request_omits_domain_filters_by_default():
    body = exa_client.build_request("diwali")
    assert "includeDomains" not in body and "excludeDomains" not in body


def test_request_includes_domain_filters_when_given():
    body = exa_client.build_request("diwali", include_domains=["a.com"], exclude_domains=["b.com"])
    assert body["includeDomains"] == ["a.com"]
    assert body["excludeDomains"] == ["b.com"]


def test_request_carries_no_deprecated_parameters():
    # Listed in the module docstring; this pins them out of the payload.
    body = exa_client.build_request("diwali")
    deprecated = {"useAutoprompt", "includeUrls", "excludeUrls", "livecrawl",
                  "numSentences", "highlightsPerUrl", "tokensNum"}
    assert deprecated.isdisjoint(body)


def test_contents_can_be_overridden():
    body = exa_client.build_request("diwali", contents={"text": {"maxCharacters": 100}})
    assert body["contents"] == {"text": {"maxCharacters": 100}}


def test_build_request_does_not_mutate_the_default_contents():
    exa_client.build_request("a", contents={"highlights": True})["contents"]["extra"] = 1
    assert exa_client.DEFAULT_CONTENTS == {"highlights": True}


# --- availability / failure ----------------------------------------------

def test_is_available_false_without_key(monkeypatch):
    monkeypatch.setattr(exa_client, "exa_api_key", lambda: None)
    assert exa_client.is_available() is False


def test_is_available_true_with_key(fake_key):
    assert exa_client.is_available() is True


def test_search_raises_without_key(monkeypatch):
    monkeypatch.setattr(exa_client, "exa_api_key", lambda: None)
    with pytest.raises(exa_client.ExaError):
        exa_client.search("diwali")


# --- caching --------------------------------------------------------------

def test_search_without_conn_calls_api_and_does_not_cache(spy):
    response, key, cached = exa_client.search("diwali")
    assert (response, key, cached) == (SAMPLE_RESPONSE, None, False)
    assert len(spy) == 1


def test_first_search_hits_the_api(conn, spy):
    _, key, cached = exa_client.search("diwali", conn=conn)
    assert cached is False and key and len(spy) == 1


def test_repeat_search_is_served_from_cache(conn, spy):
    exa_client.search("diwali", conn=conn)
    response, _, cached = exa_client.search("diwali", conn=conn)
    assert (response, cached) == (SAMPLE_RESPONSE, True)
    assert len(spy) == 1, "second identical search must not spend API budget"


def test_repeat_search_returns_the_same_cache_key(conn, spy):
    _, first, _ = exa_client.search("diwali", conn=conn)
    _, second, _ = exa_client.search("diwali", conn=conn)
    assert first == second


def test_different_query_is_a_separate_cache_entry(conn, spy):
    exa_client.search("diwali", conn=conn)
    exa_client.search("holi", conn=conn)
    assert len(spy) == 2


def test_different_num_results_is_a_separate_cache_entry(conn, spy):
    # The cache keys on the whole request body, so a parameter change must not
    # silently return results shaped for the previous call.
    exa_client.search("diwali", conn=conn, num_results=3)
    exa_client.search("diwali", conn=conn, num_results=10)
    assert len(spy) == 2


def test_api_key_is_not_part_of_the_cache_key(conn, spy, monkeypatch):
    exa_client.search("diwali", conn=conn)
    monkeypatch.setattr(exa_client, "exa_api_key", lambda: "rotated-key")
    _, _, cached = exa_client.search("diwali", conn=conn)
    assert cached is True, "rotating the key must not invalidate cached results"


# --- evidence mapping -----------------------------------------------------

def test_to_evidence_maps_every_result():
    assert len(exa_client.to_evidence(SAMPLE_RESPONSE)) == 2


def test_to_evidence_records_source_and_kind():
    evidence = exa_client.to_evidence(SAMPLE_RESPONSE)[0]
    assert evidence.kind is EvidenceKind.SEARCH_RESULT
    assert evidence.url == "https://example.com/diwali-saree"
    assert evidence.title == "Diwali Saree Demand 2026"


def test_to_evidence_joins_multiple_highlights():
    # Relevance is spread across excerpts, so keeping only the first loses it.
    evidence = exa_client.to_evidence(SAMPLE_RESPONSE)[1]
    assert evidence.snippet == "Festival season lifts orders.\nSecond excerpt."


def test_to_evidence_links_back_to_the_cached_response():
    evidence = exa_client.to_evidence(SAMPLE_RESPONSE, cache_key="k123")[0]
    assert evidence.cache_key == "k123"


def test_to_evidence_stamps_retrieval_time():
    when = datetime(2026, 9, 13, tzinfo=timezone.utc)
    assert exa_client.to_evidence(SAMPLE_RESPONSE, retrieved_at=when)[0].retrieved_at == when


def test_to_evidence_can_be_limited():
    assert len(exa_client.to_evidence(SAMPLE_RESPONSE, limit=1)) == 1


def test_to_evidence_handles_a_result_without_highlights():
    response = {"results": [{"title": "t", "url": "u"}]}
    assert exa_client.to_evidence(response)[0].snippet is None


def test_to_evidence_handles_an_empty_response():
    assert exa_client.to_evidence({}) == []
    assert exa_client.to_evidence(None) == []
