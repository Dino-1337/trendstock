"""Timestamped logging for the pipeline.

start.ps1 redirects uvicorn's stdout/stderr into backend.log, so anything
logged to stdout here lands there with a timestamp automatically. Nothing
extra to wire up — run the server and `Get-Content backend.log -Wait -Tail 20`.

What gets logged is deliberately the stuff that is otherwise invisible and
that we have already been burned by: which tagger actually produced a result,
whether Groq was even reachable, what the relevance gate dropped, and cache
hit rates. A silent fallback to rule-based tagging looks identical to a
working LLM from the outside — that ambiguity is exactly what cost us a
debugging cycle earlier, so it is now written down every run.

NEVER log the API key, or any value read from the environment.
"""

import logging
import os
import sys

LOG_LEVEL = os.getenv("TRENDSTOCK_LOG_LEVEL", "INFO").upper()

_CONFIGURED = False


def configure():
    """Idempotent: safe to call from both the API and run_pipeline.py."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger("trendstock")
    root.setLevel(LOG_LEVEL)
    root.handlers.clear()
    root.addHandler(handler)
    # Don't also bubble up to uvicorn's root handler, or every line prints twice.
    root.propagate = False

    _CONFIGURED = True


def get_logger(name):
    configure()
    return logging.getLogger(f"trendstock.{name}")
