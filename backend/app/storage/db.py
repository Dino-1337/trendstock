"""SQLite connection handling and schema for derived knowledge.

Why SQLite arrives now, and what it does *not* replace:

Raw daily trend snapshots stay flat JSON under data/raw/<date>/ - they are
append-only archival blobs and files serve that fine. What files serve badly is
everything the dashboard and the (planned) chatbot need: "which events land in
the next 30 days", "what did we conclude about ethnic wear", "why did we
conclude it". Those are queries, and today trend_history.py answers its version
of them by globbing and re-parsing every snapshot on disk on every run - a cost
that grows with each day the pipeline runs.

Three kinds of data live here, deliberately kept separate:

1. api_cache      - raw upstream responses (Calendarific, Exa). Re-fetchable,
                    TTL'd, purely an optimization. Losing it costs API calls,
                    not knowledge.
2. events /       - derived knowledge: resolved event dates and the agent's
   category_event_signals   conclusions about category demand. What the
                    dashboard reads.
3. evidence       - provenance: which snippet, source or calendar entry led to
                    each conclusion. Cheap to record now, impossible to
                    reconstruct later, and the difference between a future
                    chatbot citing real sources and inventing a rationale.
"""

import sqlite3
from contextlib import contextmanager

from app.storage.paths import DB_PATH

SCHEMA_VERSION = 1

_SCHEMA = """
-- 1. CACHE -------------------------------------------------------------
-- Keyed by a hash of (provider, request). Unlike the tag cache in
-- app/tagging/cache.py, this one needs real TTLs: calendar data is stable for
-- months, search results go stale in days.
CREATE TABLE IF NOT EXISTS api_cache (
    key         TEXT PRIMARY KEY,
    provider    TEXT NOT NULL,
    request     TEXT NOT NULL,          -- JSON, kept for debuggability
    response    TEXT NOT NULL,          -- JSON body as returned
    fetched_at  TEXT NOT NULL,          -- ISO-8601 UTC
    expires_at  TEXT                    -- ISO-8601 UTC; NULL = never expires
);
CREATE INDEX IF NOT EXISTS idx_api_cache_provider ON api_cache (provider);
CREATE INDEX IF NOT EXISTS idx_api_cache_expires  ON api_cache (expires_at);

-- 2. DERIVED KNOWLEDGE -------------------------------------------------
-- Events come from a calendar provider, never from model recall: Diwali, Eid
-- and Navratri are lunar/lunisolar and shift every year, which is exactly the
-- kind of fact an LLM states confidently and wrongly.
CREATE TABLE IF NOT EXISTS events (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    event_type        TEXT,             -- national | regional | religious | seasonal
    regions           TEXT,             -- JSON array; [] means pan-India
    event_date        TEXT NOT NULL,    -- ISO-8601 date, resolved for this year
    date_is_estimated INTEGER NOT NULL DEFAULT 0,   -- lunar-uncertainty flag
    source            TEXT,             -- provider that resolved the date
    raw               TEXT,             -- original provider payload
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE (name, event_date)
);
CREATE INDEX IF NOT EXISTS idx_events_date ON events (event_date);

-- One row per (category, event). Rewritten in place when a Phase 2 refresh
-- deepens what Phase 1 concluded, so the dashboard always reads current state
-- while `phase` records how that conclusion was reached.
CREATE TABLE IF NOT EXISTS category_event_signals (
    id                INTEGER PRIMARY KEY,
    category          TEXT NOT NULL,
    event_id          INTEGER NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    demand_lift       TEXT,             -- low | medium | high
    confidence        TEXT,             -- low | medium | high
    lead_time_days    INTEGER,          -- how early demand starts rising
    reasoning_summary TEXT,
    phase             TEXT NOT NULL,    -- bulk | event_refresh
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE (category, event_id)
);
CREATE INDEX IF NOT EXISTS idx_signals_category ON category_event_signals (category);
CREATE INDEX IF NOT EXISTS idx_signals_event    ON category_event_signals (event_id);

-- 3. PROVENANCE --------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence (
    id           INTEGER PRIMARY KEY,
    signal_id    INTEGER NOT NULL REFERENCES category_event_signals (id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,         -- search_result | calendar_entry | model_output
    url          TEXT,
    title        TEXT,
    snippet      TEXT,
    retrieved_at TEXT NOT NULL,
    cache_key    TEXT                   -- links back to api_cache for the full response
);
CREATE INDEX IF NOT EXISTS idx_evidence_signal ON evidence (signal_id);
"""


def connect(db_path=None):
    """Open a connection with the settings this project needs everywhere.

    WAL matters because FastAPI serves reads while the pipeline writes; the
    default rollback journal would have them blocking each other.
    """
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn):
    """Create tables if absent and stamp the schema version.

    PRAGMA user_version is the migration hook: when the schema changes, bump
    SCHEMA_VERSION and branch here on the stored value.
    """
    conn.executescript(_SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return conn


@contextmanager
def get_db(db_path=None):
    """Context manager yielding an initialized connection, committing on clean
    exit and rolling back on error."""
    conn = connect(db_path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def schema_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]
