"""Central .env loading and API-key access.

The dotenv bootstrap used to live inside app/tagging/llm_groq.py, which meant
any second module needing a key would have copied it - the same drift that had
seven modules each re-deriving the data root before app/storage/paths.py.

Keys are read through functions rather than captured into module constants at
import time so tests can monkeypatch the environment, and so a key added to
.env after the process started is still picked up on reload.
"""

import os

from dotenv import load_dotenv

from app.storage.paths import BACKEND_DIR

_REPO_ROOT = BACKEND_DIR.parent

# Repo root first, then backend/ - override=False so a real environment
# variable always beats the file.
for _candidate in (_REPO_ROOT / ".env", BACKEND_DIR / ".env"):
    if _candidate.exists():
        load_dotenv(dotenv_path=_candidate, override=False)


def _first_env(*names):
    """Return the first name that is set to a non-empty value.

    Several keys are accepted per provider because the names in .env do not all
    match the canonical spelling (CALENDIRIFIC is missing an 'a'). Rather than
    require an edit that would silently break the running setup, both spellings
    resolve - the canonical one wins if both are present.
    """
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return None


def groq_api_key():
    return _first_env("GROQ_API_KEY")


def exa_api_key():
    return _first_env("EXA_API_KEY", "EXA_AI_API_KEY")


def calendarific_api_key():
    return _first_env("CALENDARIFIC_API_KEY", "CALENDARIFIC", "CALENDIRIFIC")


def has_groq():
    return bool(groq_api_key())


def has_exa():
    return bool(exa_api_key())


def has_calendarific():
    return bool(calendarific_api_key())
