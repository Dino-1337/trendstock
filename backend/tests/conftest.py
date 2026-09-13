"""Session-wide test guardrails."""

import pytest

from app.catalog.load_products import CURRENT_CATALOG_CSV


@pytest.fixture(autouse=True, scope="session")
def preserve_real_catalog():
    """Never let a test run destroy the catalog a developer uploaded through
    the UI.

    Several tests exercise the real upload path, which writes to a single
    shared file (data/uploads/current_catalog.csv). Their individual cleanups
    used to delete it outright — so running `pytest` silently wiped the live
    catalog, and the dashboard came back empty for reasons that looked like an
    app bug. This snapshots the file once per session and puts it back
    afterwards, whatever the tests did to it in between.
    """
    backup = CURRENT_CATALOG_CSV.read_bytes() if CURRENT_CATALOG_CSV.exists() else None
    try:
        yield
    finally:
        if backup is None:
            CURRENT_CATALOG_CSV.unlink(missing_ok=True)
        else:
            CURRENT_CATALOG_CSV.parent.mkdir(parents=True, exist_ok=True)
            CURRENT_CATALOG_CSV.write_bytes(backup)


@pytest.fixture(autouse=True)
def no_groq_network_calls(monkeypatch):
    """Tests must never make real network calls (project constraint - see
    docs/checklist-backend.md). Several endpoint-level tests exercise the
    full tagging pipeline (app/tagging/tagger.py tries Groq before falling
    back to the rule-based tagger), so without this, a cold disk cache would
    make a real Groq API call during a normal test run.

    Forcing GROQ_API_KEY unset for every test - regardless of what's in the
    real .env or already warmed into data/cache/tags/ - guarantees every test
    runs the deterministic rule-based tagger. Tests that specifically need to
    exercise the Groq code path (llm_groq validation/fallback/batching) mock
    the HTTP call itself and set a fake key locally within that test.
    """
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
