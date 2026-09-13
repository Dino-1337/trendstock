"""Tagging orchestration (app/tagging/tagger.py): cache-first, then Groq if
available, falling back to the rule-based tagger on any failure. Groq itself
is mocked throughout - no network calls."""

from app.tagging import llm_groq, tagger
from app.tagging.base import TagResult
from app.tagging.vocabulary import get_vocabulary


def test_cache_hit_skips_llm_entirely(tmp_path, monkeypatch):
    vocabulary = get_vocabulary()
    calls = []
    monkeypatch.setattr(llm_groq, "is_available", lambda: True)
    monkeypatch.setattr(llm_groq, "tag_batch", lambda texts, vocab: calls.append(texts) or {})

    # Warm the cache directly, bypassing both backends.
    tagger.tag_batch(
        [("p1", "nike sneakers")], "test-ns", vocabulary=vocabulary, cache_dir=tmp_path,
    )
    calls.clear()
    monkeypatch.setattr(llm_groq, "is_available", lambda: (_ for _ in ()).throw(AssertionError("should not be called")))

    results = tagger.tag_batch(
        [("p1", "nike sneakers")], "test-ns", vocabulary=vocabulary, cache_dir=tmp_path,
    )
    assert results["p1"].tags == ["Sneakers"]


def test_llm_result_used_when_available_and_valid(tmp_path, monkeypatch):
    vocabulary = get_vocabulary()

    def fake_llm_tag_batch(texts, vocab):
        return {t: TagResult(tags=["Sneakers"], source="llm_groq") for t in texts}

    monkeypatch.setattr(llm_groq, "is_available", lambda: True)
    monkeypatch.setattr(llm_groq, "tag_batch", fake_llm_tag_batch)

    results = tagger.tag_batch(
        [("p1", "some text")], "test-ns", vocabulary=vocabulary, cache_dir=tmp_path,
    )
    assert results["p1"].source == "llm_groq"
    assert results["p1"].tags == ["Sneakers"]


def test_llm_failure_falls_back_to_rule_based(tmp_path, monkeypatch):
    vocabulary = get_vocabulary()

    def raising_llm_tag_batch(texts, vocab):
        raise RuntimeError("simulated Groq outage")

    monkeypatch.setattr(llm_groq, "is_available", lambda: True)
    monkeypatch.setattr(llm_groq, "tag_batch", raising_llm_tag_batch)

    results = tagger.tag_batch(
        [("p1", "nike sneakers")], "test-ns", vocabulary=vocabulary, cache_dir=tmp_path,
    )
    assert results["p1"].source == "rule_based"
    assert results["p1"].tags == ["Sneakers"]


def test_llm_unavailable_uses_rule_based_without_calling_it(tmp_path, monkeypatch):
    vocabulary = get_vocabulary()
    monkeypatch.setattr(llm_groq, "is_available", lambda: False)
    monkeypatch.setattr(
        llm_groq, "tag_batch",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called when unavailable")),
    )

    results = tagger.tag_batch(
        [("p1", "nike sneakers")], "test-ns", vocabulary=vocabulary, cache_dir=tmp_path,
    )
    assert results["p1"].source == "rule_based"


def test_successful_result_is_cached_for_next_call(tmp_path, monkeypatch):
    vocabulary = get_vocabulary()
    call_count = {"n": 0}

    def fake_llm_tag_batch(texts, vocab):
        call_count["n"] += 1
        return {t: TagResult(tags=["Sneakers"], source="llm_groq") for t in texts}

    monkeypatch.setattr(llm_groq, "is_available", lambda: True)
    monkeypatch.setattr(llm_groq, "tag_batch", fake_llm_tag_batch)

    tagger.tag_batch([("p1", "nike sneakers")], "test-ns", vocabulary=vocabulary, cache_dir=tmp_path)
    tagger.tag_batch([("p1", "nike sneakers")], "test-ns", vocabulary=vocabulary, cache_dir=tmp_path)

    assert call_count["n"] == 1  # second call was a cache hit


def test_mixed_batch_partial_cache_hit(tmp_path, monkeypatch):
    """One cached item + one new item: only the new item should reach the
    (mocked) LLM, and both results should come back correctly."""
    vocabulary = get_vocabulary()

    monkeypatch.setattr(llm_groq, "is_available", lambda: True)
    monkeypatch.setattr(
        llm_groq, "tag_batch",
        lambda texts, vocab: {t: TagResult(tags=["Sneakers"], source="llm_groq") for t in texts},
    )
    tagger.tag_batch([("p1", "nike sneakers")], "test-ns", vocabulary=vocabulary, cache_dir=tmp_path)

    seen_texts = []

    def fake_llm_tag_batch(texts, vocab):
        seen_texts.extend(texts)
        return {t: TagResult(tags=["Sandals"], source="llm_groq") for t in texts}

    monkeypatch.setattr(llm_groq, "tag_batch", fake_llm_tag_batch)
    results = tagger.tag_batch(
        [("p1", "nike sneakers"), ("p2", "puma slides")], "test-ns", vocabulary=vocabulary, cache_dir=tmp_path,
    )

    assert seen_texts == ["puma slides"]  # p1 was a cache hit, not re-sent
    assert results["p1"].tags == ["Sneakers"]
    assert results["p2"].tags == ["Sandals"]
