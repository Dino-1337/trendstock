"""Tagging orchestration: try Groq (batched, validated, cached), fall back to
the deterministic rule-based tagger for anything Groq doesn't handle -
missing key, network/rate-limit failure, or a response that doesn't parse.
The pipeline must never crash or hang because Groq is unavailable.

`source` on every TagResult records which backend actually produced it
(rule_based vs llm_groq), so it stays visible which path ran - this is not
hidden behind the interface, it is the whole point of exposing it.
"""

import time
from collections import Counter

from app.logging_setup import get_logger
from app.tagging import llm_groq
from app.tagging.base import TagResult
from app.tagging.cache import CACHE_DIR, TagCache
from app.tagging.rule_based import tag_text
from app.tagging.vocabulary import get_vocabulary

log = get_logger("tagging")


def tag_batch(items, cache_namespace, vocabulary=None, cache_dir=None):
    """items: list of (item_id, text) pairs.
    Returns {item_id: TagResult}.

    Cache hits skip both backends entirely. Everything else is attempted via
    Groq as ONE batched request (if a key is present); anything Groq fails to
    return a valid result for falls back to the rule-based tagger, item by
    item, so a single bad response never blanks out the whole batch.

    cache_dir defaults to the real on-disk cache; tests pass a tmp_path here
    to avoid writing into the repo's actual data/cache/tags/ as a side effect.
    """
    vocabulary = vocabulary or get_vocabulary()
    cache = TagCache(cache_namespace, vocabulary.version, cache_dir=cache_dir or CACHE_DIR)

    results = {}
    to_fetch = []  # (item_id, text)
    for item_id, text in items:
        cached = cache.get(text)
        if cached is not None:
            results[item_id] = cached
        else:
            to_fetch.append((item_id, text))

    log.info(
        "%s: %d items (%d cached, %d to tag)",
        cache_namespace, len(items), len(results), len(to_fetch),
    )

    llm_results = {}
    if not to_fetch:
        pass
    elif not llm_groq.is_available():
        log.warning(
            "%s: Groq unavailable (no GROQ_API_KEY) - rule-based only", cache_namespace
        )
    else:
        started = time.monotonic()
        try:
            llm_results = llm_groq.tag_batch([text for _, text in to_fetch], vocabulary)
            log.info(
                "%s: Groq returned %d/%d in %.1fs",
                cache_namespace, len(llm_results), len(to_fetch), time.monotonic() - started,
            )
        except Exception as exc:
            # Network error, rate limit, malformed response, missing key
            # discovered mid-call, whatever - Groq simply didn't come through
            # this run. Every item below falls back to rule-based.
            log.warning(
                "%s: Groq failed after %.1fs (%s: %s) - falling back to rule-based",
                cache_namespace, time.monotonic() - started, type(exc).__name__, exc,
            )
            llm_results = {}

    for item_id, text in to_fetch:
        results[item_id] = _merge(llm_results.get(text), tag_text(text, vocabulary))
        cache.set(text, results[item_id])

    cache.flush()

    by_source = Counter(r.source for r in results.values())
    untagged = [item_id for item_id, r in results.items() if not r.tags]
    log.info("%s: sources=%s untagged=%d", cache_namespace, dict(by_source), len(untagged))
    if untagged:
        # Worth naming: an untagged product silently matches nothing, and an
        # untagged trend is dropped by the relevance gate entirely.
        log.warning("%s: no tags for %s", cache_namespace, untagged[:10])

    return results


def _merge(llm_result, rule_result):
    """Union the two taggers rather than picking one.

    The LLM is only trusted to ADD to the deterministic result, never to replace
    it. This closes a real false-negative found in live testing: Groq can return
    a successful, well-formed, EMPTY tag list (verified on "nike air max" and on
    every Tshirts/Slides product in the sample catalog). Because that is not an
    exception, the old code accepted it and the rule-based tagger — which gets
    those right every time — never ran. On the trend side that was worse than a
    weak match: an untagged trend fails the relevance gate and disappears.

    Union costs nothing (the rule-based pass is local and deterministic) and
    keeps what each side is genuinely good at: exact vocabulary matching from
    rules, synonym/context understanding ("trainers" -> Sneakers) from the LLM.
    It does NOT fix LLM hallucination (a false positive) - that is a separate,
    lesser problem than dropping real signal.
    """
    if llm_result is None:
        return rule_result
    if not llm_result.tags:
        return rule_result

    tags = sorted(set(llm_result.tags) | set(rule_result.tags))
    if tags == sorted(set(llm_result.tags)):
        return llm_result  # rule-based added nothing; keep source as-is

    return TagResult(
        tags=tags,
        source="llm_groq+rule_based",
        detail=(llm_result.detail or []) + (rule_result.detail or []),
    )
