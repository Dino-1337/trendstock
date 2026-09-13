"""Groq LLM tagger (app/tagging/llm_groq.py) - fully mocked, no network calls.
Covers: validation against the controlled vocabulary (out-of-vocabulary and
wrong-case tags get discarded), batching (one HTTP call for N items), and
that failures propagate so the orchestrator (tagger.py) can fall back."""

import json

import pytest
import requests

from app.tagging import llm_groq
from app.tagging.vocabulary import get_vocabulary


class FakeResponse:
    def __init__(self, status_code=200, json_body=None):
        self.status_code = status_code
        self._json_body = json_body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._json_body


def _groq_body(content_dict):
    return {"choices": [{"message": {"content": json.dumps(content_dict)}}]}


@pytest.fixture
def vocabulary():
    return get_vocabulary()


def test_is_available_reflects_env_var(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert llm_groq.is_available() is False
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-testing")
    assert llm_groq.is_available() is True


def test_tag_batch_raises_without_api_key(monkeypatch, vocabulary):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        llm_groq.tag_batch(["nike sneakers"], vocabulary)


def test_tag_batch_valid_response(monkeypatch, vocabulary):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-testing")
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json)
        return FakeResponse(200, _groq_body({"0": ["Sneakers"], "1": []}))

    monkeypatch.setattr(llm_groq.requests, "post", fake_post)
    results = llm_groq.tag_batch(["nike sneakers", "cricket match today"], vocabulary)

    assert results["nike sneakers"].tags == ["Sneakers"]
    assert results["nike sneakers"].source == "llm_groq"
    assert results["cricket match today"].tags == []
    assert len(calls) == 1  # one HTTP call for the whole batch, not one per item


def test_tag_batch_discards_out_of_vocabulary_tags(monkeypatch, vocabulary):
    """The model must SELECT from the vocabulary, never free-generate. Any tag
    not in the vocabulary is discarded, not trusted."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-testing")

    def fake_post(url, headers, json, timeout):
        return FakeResponse(200, _groq_body({"0": ["Sneakers", "Trainers", "Made Up Tag"]}))

    monkeypatch.setattr(llm_groq.requests, "post", fake_post)
    results = llm_groq.tag_batch(["retro trainers restock"], vocabulary)

    result = results["retro trainers restock"]
    assert result.tags == ["Sneakers"]
    dropped_entries = [d for d in result.detail if "dropped_out_of_vocabulary" in d]
    assert dropped_entries
    assert "Trainers" in dropped_entries[0]["dropped_out_of_vocabulary"]
    assert "Made Up Tag" in dropped_entries[0]["dropped_out_of_vocabulary"]


def test_tag_batch_resolves_case_insensitively_to_canonical_form(monkeypatch, vocabulary):
    """Live testing showed the model doesn't reliably preserve exact case even
    when told to copy verbatim - validation must still accept it, canonicalized."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-testing")

    def fake_post(url, headers, json, timeout):
        return FakeResponse(200, _groq_body({"0": ["sneakers"]}))  # lowercase from the model

    monkeypatch.setattr(llm_groq.requests, "post", fake_post)
    results = llm_groq.tag_batch(["nike sneakers"], vocabulary)
    assert results["nike sneakers"].tags == ["Sneakers"]  # canonical casing, not the model's


def test_tag_batch_strips_markdown_fences(monkeypatch, vocabulary):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-testing")

    def fake_post(url, headers, json, timeout):
        fenced = "```json\n" + json_module_dumps({"0": ["Sneakers"]}) + "\n```"
        return FakeResponse(200, {"choices": [{"message": {"content": fenced}}]})

    def json_module_dumps(d):
        import json as _json
        return _json.dumps(d)

    monkeypatch.setattr(llm_groq.requests, "post", fake_post)
    results = llm_groq.tag_batch(["nike sneakers"], vocabulary)
    assert results["nike sneakers"].tags == ["Sneakers"]


def test_tag_batch_propagates_http_errors_for_caller_to_handle(monkeypatch, vocabulary):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-testing")

    def fake_post(url, headers, json, timeout):
        return FakeResponse(429, None)

    monkeypatch.setattr(llm_groq.requests, "post", fake_post)
    with pytest.raises(requests.exceptions.HTTPError):
        llm_groq.tag_batch(["nike sneakers"], vocabulary)


def test_tag_batch_propagates_unparseable_response(monkeypatch, vocabulary):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-testing")

    def fake_post(url, headers, json, timeout):
        return FakeResponse(200, {"choices": [{"message": {"content": "not json at all"}}]})

    monkeypatch.setattr(llm_groq.requests, "post", fake_post)
    with pytest.raises(Exception):
        llm_groq.tag_batch(["nike sneakers"], vocabulary)


def test_tag_batch_empty_input_makes_no_call(monkeypatch, vocabulary):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-testing")
    calls = []
    monkeypatch.setattr(llm_groq.requests, "post", lambda *a, **k: calls.append(1))
    assert llm_groq.tag_batch([], vocabulary) == {}
    assert calls == []
