"""General-purpose Groq chat client with Pydantic-validated structured output.

Relationship to app/tagging/llm_groq.py: that module stays as it is. It does
one specialised job - a single batched tagging call tuned around Groq's TPM
accounting - and it is covered by tests that patch its own `requests.post`.
This module is the general transport for everything else: the store-profile
pass, product enrichment and signal interpretation. The genuinely shared piece,
the model rotation list, lives here and is imported there, so the two cannot
drift.

Why plain HTTP and not a framework: the rotation below is the reason. Groq
meters rate limits per model, so a 429 is best answered by switching models,
not by sleeping - behaviour that agent frameworks model poorly and would have
to be fought to reproduce.

Tool-calling support was written here and then removed: every caller settled on
`structured()`, so the loop was dead code. The transport is deliberately plain
enough that re-adding it is small, and git has the original.
"""

import json
import time

import requests
from pydantic import ValidationError

from app.config import groq_api_key
from app.logging_setup import get_logger

log = get_logger("llm")

API_URL = "https://api.groq.com/openai/v1/chat/completions"
REQUEST_TIMEOUT = 60

# Groq meters rate limits PER MODEL, so a 429 on one model does not consume
# another's budget - rotating is strictly better than waiting when the first
# choice is exhausted. Ordered smallest/fastest first.
#
# IMPORTANT - verified against GET /openai/v1/models on 2026-09-13: the
# previous list led with `llama-3.1-8b-instant` and also contained
# `llama-3.3-70b-versatile`, and NEITHER EXISTS ON GROQ ANY MORE. Because the
# old rotation only retried on 429, the resulting 404 raised immediately and
# tagging had been silently falling back to rule-based ever since those models
# were decommissioned. Re-check this list against that endpoint when a model
# starts 404ing; do not assume a name that worked before still resolves.
MODELS = [
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
]

# Reasoning-heavier work (judging category relevance, weighing evidence) is
# worth a larger model than tagging uses, so callers can ask for this order
# instead. Same rotation rules apply.
REASONING_MODELS = [
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-20b",
]

MAX_ATTEMPTS_PER_MODEL = 2
BACKOFF_BASE_SECONDS = 0.5
MAX_BACKOFF_SECONDS = 4.0

# How many times a schema-invalid response is sent back for repair before
# giving up. Two is enough in practice: the first retry carries the actual
# validation error, which is usually sufficient to fix the shape.
MAX_REPAIR_ATTEMPTS = 2


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """No API key configured. Distinct from LLMError so callers can fall back
    silently rather than treating a missing key as a failure worth reporting."""


def is_available():
    return bool(groq_api_key())


def _retry_after_seconds(response):
    raw = (getattr(response, "headers", None) or {}).get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def chat(messages, models=None, temperature=0, max_tokens=2048,
         response_format=None):
    """One chat completion, rotating models on rate limits.

    Returns the assistant `message` dict rather than just its text, so callers
    can append it verbatim to a conversation.

    max_tokens is capped deliberately: Groq's free-tier TPM accounting reserves
    max_tokens against the budget UP FRONT, not on actual usage, so an
    oversized value can fail a request that would otherwise fit.
    """
    api_key = groq_api_key()
    if not api_key:
        raise LLMUnavailable("GROQ_API_KEY is not set")

    models = models or MODELS
    last_error = None

    for model in models:
        for attempt in range(MAX_ATTEMPTS_PER_MODEL):
            body = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if response_format:
                body["response_format"] = response_format

            response = requests.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code < 400:
                return response.json()["choices"][0]["message"]

            # Anything that is not a rate limit - most importantly 404 for a
            # decommissioned model name - is a property of THIS model, not of
            # the request. Rotate rather than raise: that is exactly the case
            # that silently disabled tagging when the llama models were
            # retired. Retrying the same dead model would never help, so move
            # on immediately instead of backing off.
            if response.status_code != 429:
                last_error = f"HTTP {response.status_code} on {model}"
                log.warning("%s failed (%s), rotating to next model",
                            model, response.status_code)
                break

            last_error = f"429 rate limited on {model}"
            wait = _retry_after_seconds(response)
            is_last_attempt = attempt == MAX_ATTEMPTS_PER_MODEL - 1

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

    raise LLMError(f"All {len(models)} Groq models rate limited ({last_error})")


def extract_json(content):
    """Parse a JSON object out of a model response.

    Models wrap JSON in markdown fences even when told not to, and the
    gpt-oss family (which rotation can fall through to) sometimes emits
    reasoning prose around the object. Both are recovered rather than
    discarding an otherwise-good response.
    """
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

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in model response")
    return json.loads(text[start : end + 1])


def structured(messages, model_cls, models=None, max_repair_attempts=MAX_REPAIR_ATTEMPTS,
               **kwargs):
    """Chat, then validate the reply against `model_cls`, repairing on failure.

    On a validation error the actual pydantic message is fed back to the model,
    which is far more effective than re-asking blindly - the model is told
    exactly which field was wrong and why.

    NOTE: response_format={"type":"json_object"} is deliberately NOT set here.
    Live testing on this project found constrained decoding makes Groq fail
    outright ("max completion tokens reached before generating a valid
    document") on long prompts - see the note in app/tagging/llm_groq.py. That
    failure was tied to a ~465-term vocabulary list, so shorter prompts may be
    fine, but the safe default is to instruct JSON in the prompt and parse
    defensively. Callers who have tested it can pass response_format through.
    """
    conversation = list(messages)
    last_error = None

    for attempt in range(max_repair_attempts + 1):
        message = chat(conversation, models=models, **kwargs)
        content = message.get("content") or ""

        try:
            return model_cls.model_validate(extract_json(content))
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == max_repair_attempts:
                break
            log.warning("structured output invalid (attempt %d): %s", attempt + 1, exc)
            conversation = conversation + [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        "That response was not valid. Fix it and return ONLY the "
                        f"corrected JSON object.\n\nError:\n{exc}"
                    ),
                },
            ]

    raise LLMError(f"Could not get valid {model_cls.__name__} after "
                   f"{max_repair_attempts + 1} attempts: {last_error}")
