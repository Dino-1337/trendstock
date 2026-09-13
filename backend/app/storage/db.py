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

SCHEMA_VERSION = 4

# Tables replaced rather than migrated in place. Everything here is derived -
# rebuildable from the raw snapshots, the API caches and the catalog - so
# dropping is cheaper and clearer than writing a real migration for data that
# has no independent source of truth. Raw snapshots and api_cache are never in
# this list; those are the things that would actually cost something to lose.
_REPLACED_TABLES = {
    # v4 replaced the per-(category, event) table with one row per interpreted
    # signal, and repointed evidence at it.
    4: ["evidence", "category_event_signals"],
}

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

-- One row per interpreted signal, whether it came from the calendar (Type A)
-- or a trend feed (Type B). Both produce the same shape, which is the point:
-- a festival and a viral aesthetic are different in origin but identical in
-- what the seller needs from them - which occasions they lift, how much, and
-- how long they have to react.
--
-- Deliberately NOT one row per (signal, product) or (signal, category). The
-- match is computed at read time by intersecting `affected_occasions` with
-- enriched_products.occasions, so re-enriching a catalog or re-interpreting a
-- signal cannot leave a stale materialised cross-product behind.
CREATE TABLE IF NOT EXISTS signals (
    id                  INTEGER PRIMARY KEY,
    signal_type         TEXT NOT NULL,    -- event | trend
    name                TEXT NOT NULL,
    source              TEXT,             -- calendarific | google_trends | ...
    event_id            INTEGER REFERENCES events (id) ON DELETE CASCADE,
    event_date          TEXT,             -- ISO date; NULL for undated trends
    affected_occasions  TEXT,             -- JSON array - THE JOIN KEY
    affected_categories TEXT,             -- JSON array, vocabulary tags
    audience            TEXT,             -- women | men | unisex | kids | null
    demand_lift         TEXT,             -- low | medium | high
    confidence          TEXT,             -- low | medium | high
    lead_time_days      INTEGER,          -- how early demand starts rising
    reasoning           TEXT,
    phase               TEXT NOT NULL,    -- bulk | refresh
    relevant            INTEGER NOT NULL DEFAULT 1,  -- survived the relevance judgement
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (signal_type, name, event_date)
);
CREATE INDEX IF NOT EXISTS idx_signals_type ON signals (signal_type);
CREATE INDEX IF NOT EXISTS idx_signals_date ON signals (event_date);

-- The seller's business context, derived once from their catalog and reused
-- as grounding for every agent call. Without it the agent judges "does Diwali
-- lift ethnic wear" in the abstract; with it, "does Diwali lift ethnic wear
-- for THIS store". It also keeps prompts small - re-sending a whole catalog on
-- every call wastes the same TPM budget llm_groq.py already had to tune around.
--
-- Computed columns (counts, price bands) come straight from the CSV and are
-- always correct. Inferred columns (positioning, audience) come from the model
-- and may be wrong, which is why `inference_source` records how each profile
-- was produced.
CREATE TABLE IF NOT EXISTS store_profile (
    id                  INTEGER PRIMARY KEY,
    catalog_fingerprint TEXT NOT NULL,   -- hash of the catalog; changes invalidate
    product_count       INTEGER NOT NULL,
    variant_count       INTEGER,
    price_min           REAL,
    price_median        REAL,
    price_max           REAL,
    top_categories      TEXT,            -- JSON array
    product_types       TEXT,            -- JSON array
    vendors             TEXT,            -- JSON array
    store_type          TEXT,
    target_audience     TEXT,
    price_positioning   TEXT,
    style_descriptors   TEXT,            -- JSON array
    summary             TEXT,
    inference_source    TEXT NOT NULL,   -- computed | computed+llm
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_profile_fingerprint
    ON store_profile (catalog_fingerprint);

-- Per-product enrichment. `occasions` is the column that matters: it is the
-- join key against a signal's affected_occasions, and the reason a festival
-- can reach a product at all. Category alone could never express that link -
-- "Diwali" is not a kind of saree, but both are `festive`.
--
-- Scoped by catalog_fingerprint so a re-uploaded catalog enriches fresh
-- instead of inheriting conclusions about products that may have changed.
CREATE TABLE IF NOT EXISTS enriched_products (
    id                  INTEGER PRIMARY KEY,
    catalog_fingerprint TEXT NOT NULL,
    product_id          TEXT NOT NULL,
    title               TEXT,
    categories          TEXT,            -- JSON array of vocabulary tags
    occasions           TEXT,            -- JSON array, closed occasion set
    materials           TEXT,            -- JSON array
    audience            TEXT,            -- women | men | unisex | kids
    style_descriptors   TEXT,            -- JSON array
    price_tier          TEXT,            -- budget | mid | premium (computed)
    source              TEXT NOT NULL,   -- rule_based | rule_based+llm
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (catalog_fingerprint, product_id)
);
CREATE INDEX IF NOT EXISTS idx_enriched_fingerprint
    ON enriched_products (catalog_fingerprint);

-- 3. PROVENANCE --------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence (
    id           INTEGER PRIMARY KEY,
    signal_id    INTEGER NOT NULL REFERENCES signals (id) ON DELETE CASCADE,
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
    """Create tables if absent, applying any pending replacements first.

    PRAGMA user_version is the migration hook. Tables listed in
    _REPLACED_TABLES for a version newer than the stored one are dropped
    before the schema is re-applied, because CREATE TABLE IF NOT EXISTS would
    otherwise silently leave an old shape in place - the failure mode being a
    table that looks fine until a query hits a column that is not there.
    """
    current = schema_version(conn)

    if current < SCHEMA_VERSION:
        for version in sorted(_REPLACED_TABLES):
            if current < version <= SCHEMA_VERSION:
                for table in _REPLACED_TABLES[version]:
                    conn.execute(f"DROP TABLE IF EXISTS {table}")

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
