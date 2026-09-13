"""Groq-backed LLM tagger.

Model: llama-3.1-8b-instant. Chosen specifically for Groq's free-tier daily
request cap (~14,400/day) vs ~1,000/day for most other free models and ~500
for Llama 4 Maverick - see https://console.groq.com/docs/rate-limits. Free
tier is roughly 30 RPM / 6,000 TPM, and TPM is the real constraint here, not
the daily cap, which is why callers batch every item from a run into ONE
request instead of one call per item (see tag_batch below and tagger.py).

No hard dependency on any LLM SDK - this is a plain `requests` call to Groq's
OpenAI-compatible endpoint, since `requests` is already a project dependency
and Groq's API needs nothing SDK-specific.

The model is instructed to SELECT tags from the supplied controlled
vocabulary only. It is not trusted to obey that on its own: every tag in the
response is resolved against Vocabulary.canonicalize_tag() (case-insensitive
- live testing showed the model doesn't reliably preserve exact case even
when told to copy verbatim) and anything that still isn't a real vocabulary
term - invented, rephrased, or malformed - is discarded before it ever
reaches a caller.

GROQ_API_KEY lives in the repo root .env in this project (not backend/.env),
resolved by an explicit path rather than cwd, since the API runs with
cwd=backend/ and run_pipeline.py may be invoked from elsewhere. The key is
never logged, printed, or included in any exception message raised here.
"""

import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from app.logging_setup import get_logger
from app.tagging.base import TagResult

log = get_logger("groq")

# Groq meters rate limits PER MODEL, so a 429 on one model does not consume
# another's budget - rotating is strictly better than waiting when the first
# choice is exhausted. Ordered cheapest/fastest first; all are on this key's
# model list (verified via GET /openai/v1/models).
#
# llama-3.1-8b-instant leads because its free-tier daily allowance is by far
# the largest (~14,400 req/day vs ~1,000 for most others). The rest are
# fallbacks used only when it 429s.
MODELS = [
    "llama-3.1-8b-instant",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "llama-3.3-70b-versatile",
]

MODEL = MODELS[0]  # kept for callers/tests that reference a single default

# Bounded, short backoff. This runs inside an HTTP request, so waiting minutes
# is not an option - a slow dashboard is worse than a rule-based tag. We retry
# briefly, honour Retry-After when the server sends a short one, and otherwise
# rotate to the next model rather than sleeping.
MAX_ATTEMPTS_PER_MODEL = 2
BACKOFF_BASE_SECONDS = 0.5
MAX_BACKOFF_SECONDS = 4.0
API_URL = "https://api.groq.com/openai/v1/chat/completions"
REQUEST_TIMEOUT = 30

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR.parent
for _candidate in (_REPO_ROOT / ".env", _BACKEND_DIR / ".env"):
    if _candidate.exists():
        load_dotenv(dotenv_path=_candidate, override=False)


def is_available():
    return bool(os.getenv("GROQ_API_KEY"))


def _build_prompt(texts, vocabulary):
    numbered = "\n".join(f"{i}: {t}" for i, t in enumerate(texts))
    tag_list = ", ".join(vocabulary.llm_candidate_tags)
    return (
        "You are a tagging assistant for a niche e-commerce trend tool. For "
        "each numbered item below, select zero or more tags that apply "
        "STRICTLY from this fixed list of allowed tags. Copy tags exactly as "
        "written; never invent, rephrase, pluralize, or translate a tag.\n\n"
        f"ALLOWED TAGS:\n{tag_list}\n\n"
        "ITEMS:\n"
        f"{numbered}\n\n"
        "Most items will be completely unrelated to shopping (sports "
        "results, politics, celebrity news) - for those, return an empty "
        "array. Only tag an item if it is genuinely about a product, "
        "clothing/footwear/accessory category, or a purchasable good.\n\n"
        "Respond with ONLY a single JSON object (no prose, no markdown "
        'fences) mapping each item\'s number as a string to an array of '
        'matching tags, e.g. {"0": ["Sneakers"], "1": [], "2": ["Sandals"]}. '
        "Every item number from the list above must be a key in the object."
    )


def _call_groq(prompt, api_key):
    # NOTE: response_format={"type": "json_object"} was tried and dropped -
    # live testing showed it makes Groq fail outright ("max completion tokens
    # reached before generating a valid document", i.e. constrained decoding
    # never converges) once the prompt includes our ~465-term allowed-tag
    # list, even at max_tokens=2048. A plain call with a JSON instruction in
    # the prompt text reliably returns a short, valid JSON object instead -
    # so we parse defensively (see _extract_json) rather than rely on the
    # API to guarantee the shape.
    #
    # max_tokens matters more than it looks: Groq's free-tier TPM accounting
    # reserves max_tokens against the budget UP FRONT, not just actual usage
    # - live testing hit "Requested 6393 tokens, Limit 6000" on a single,
    # first-call-of-the-window request, entirely because max_tokens=4096 was
    # being added to the ~2500-token prompt. The JSON response for a batch of
    # ~10 short items is at most a few hundred tokens, so 1024 leaves ample
    # headroom without eating the TPM budget for nothing.
    last_error = None

    for model in MODELS:
        for attempt in range(MAX_ATTEMPTS_PER_MODEL):
            response = requests.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 1024,
                },
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code != 429:
                response.raise_for_status()
                log.info("tagged via %s", model)
                return response.json()["choices"][0]["message"]["content"]

            last_error = f"429 rate limited on {model}"
            wait = _retry_after_seconds(response)
            is_last_attempt = attempt == MAX_ATTEMPTS_PER_MODEL - 1

            # Only sleep if the server says the window reopens soon AND we
            # still have an attempt left on this model. Otherwise rotate -
            # another model's budget is untouched by this model's 429.
            if wait is not None and wait <= MAX_BACKOFF_SECONDS and not is_last_attempt:
                log.warning("%s rate limited, retrying in %.1fs", model, wait)
                time.sleep(wait)
                continue

            if not is_last_attempt:
                backoff = min(BACKOFF_BASE_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
                log.warning("%s rate limited, backing off %.1fs", model, backoff)
                time.sleep(backoff)
                continue

            log.warning("%s exhausted, rotating to next model", model)
            break

    raise requests.HTTPError(
        f"All {len(MODELS)} Groq models rate limited ({last_error})"
    )


def _retry_after_seconds(response):
    """Groq sends Retry-After (seconds, or occasionally a float) on 429."""
    raw = (getattr(response, "headers", None) or {}).get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _extract_json(content):
    """The model was told to respond with ONLY a JSON object, but models
    sometimes wrap it in markdown fences anyway. Strip those, then parse."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Some models (notably the gpt-oss family, which rotation can fall through
    # to) emit prose or reasoning around the object instead of the bare JSON
    # they were asked for. Recover the outermost {...} block rather than
    # discarding an otherwise-good response.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in model response")
    return json.loads(text[start : end + 1])


def tag_batch(texts, vocabulary):
    """texts: list of strings. Returns {text: TagResult} for every text that
    got a valid response. Raises on any failure (missing key, network error,
    bad status, unparseable response) - callers are expected to catch broadly
    and fall back to the rule-based tagger; this function never partially
    degrades silently, it either returns a full batch or raises.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    if not texts:
        return {}

    prompt = _build_prompt(texts, vocabulary)
    content = _call_groq(prompt, api_key)
    parsed = _extract_json(content)
    if not isinstance(parsed, dict):
        raise ValueError("Groq response was not a JSON object")

    results = {}
    for i, text in enumerate(texts):
        raw_tags = parsed.get(str(i), [])
        if not isinstance(raw_tags, list):
            raw_tags = []
        canonical = []
        dropped = []
        for t in raw_tags:
            resolved = vocabulary.canonicalize_tag(t) if isinstance(t, str) else None
            (canonical if resolved else dropped).append(resolved or t)
        valid_tags = sorted(set(canonical))
        detail = [{"tag": t, "kind": "llm"} for t in valid_tags]
        if dropped:
            detail.append({"dropped_out_of_vocabulary": dropped})
        results[text] = TagResult(tags=valid_tags, source="llm_groq", detail=detail)

    return results
