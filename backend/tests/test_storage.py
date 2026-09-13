from datetime import datetime, timedelta, timezone

import pytest

from app.storage import api_cache, db


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    db.init_db(connection)
    yield connection
    connection.close()


NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


# --- schema ---------------------------------------------------------------

def test_init_db_creates_expected_tables(conn):
    names = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"api_cache", "events", "signals", "evidence"} <= names


def test_init_db_stamps_schema_version(conn):
    assert db.schema_version(conn) == db.SCHEMA_VERSION


def test_init_db_is_idempotent(conn):
    db.init_db(conn)
    db.init_db(conn)
    assert db.schema_version(conn) == db.SCHEMA_VERSION


def test_foreign_keys_are_enforced(conn):
    # Guards the provenance chain: evidence must never outlive its signal.
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO evidence (signal_id, kind, retrieved_at) VALUES (?, ?, ?)",
            (999, "search_result", NOW.isoformat()),
        )
        conn.commit()


def test_deleting_a_signal_cascades_to_evidence(conn):
    conn.execute(
        """INSERT INTO signals (id, signal_type, name, event_date, phase, created_at, updated_at)
           VALUES (1, 'event', 'Diwali', '2026-11-08', 'bulk', ?, ?)""",
        (NOW.isoformat(), NOW.isoformat()),
    )
    conn.execute(
        "INSERT INTO evidence (signal_id, kind, retrieved_at) VALUES (1, 'search_result', ?)",
        (NOW.isoformat(),),
    )
    conn.execute("DELETE FROM signals WHERE id = 1")
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0


def test_one_signal_per_type_name_and_date(conn):
    stmt = """INSERT INTO signals (signal_type, name, event_date, phase, created_at, updated_at)
              VALUES ('event', 'Diwali', '2026-11-08', 'bulk', ?, ?)"""
    conn.execute(stmt, (NOW.isoformat(), NOW.isoformat()))
    with pytest.raises(Exception):
        conn.execute(stmt, (NOW.isoformat(), NOW.isoformat()))


def test_replaced_tables_are_dropped_on_upgrade(tmp_path):
    """A stale table shape must not survive an upgrade.

    CREATE TABLE IF NOT EXISTS would silently leave the old columns in place,
    and the failure would surface later as a query hitting a column that is
    not there.
    """
    path = tmp_path / "old.db"
    conn = db.connect(path)
    conn.execute("CREATE TABLE category_event_signals (id INTEGER PRIMARY KEY)")
    conn.execute("PRAGMA user_version = 3")
    conn.commit()

    db.init_db(conn)

    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "category_event_signals" not in names
    assert "signals" in names
    assert db.schema_version(conn) == db.SCHEMA_VERSION
    conn.close()


# --- api cache ------------------------------------------------------------

def test_get_returns_none_when_absent(conn):
    assert api_cache.get(conn, "exa", {"q": "diwali"}) is None


def test_set_then_get_roundtrips(conn):
    api_cache.set(conn, "exa", {"q": "diwali"}, {"results": [1, 2]}, now=NOW)
    assert api_cache.get(conn, "exa", {"q": "diwali"}, now=NOW) == {"results": [1, 2]}


def test_key_is_order_independent(conn):
    # A request dict built in a different order must hit the same entry,
    # otherwise the cache silently never hits.
    api_cache.set(conn, "exa", {"a": 1, "b": 2}, {"ok": True}, now=NOW)
    assert api_cache.get(conn, "exa", {"b": 2, "a": 1}, now=NOW) == {"ok": True}


def test_key_is_provider_scoped(conn):
    api_cache.set(conn, "exa", {"q": "x"}, {"from": "exa"}, now=NOW)
    assert api_cache.get(conn, "calendarific", {"q": "x"}, now=NOW) is None


def test_entry_without_ttl_never_expires(conn):
    api_cache.set(conn, "calendarific", {"year": 2026}, {"holidays": []}, now=NOW)
    far_future = NOW + timedelta(days=3650)
    assert api_cache.get(conn, "calendarific", {"year": 2026}, now=far_future) is not None


def test_expired_entry_reads_as_missing(conn):
    api_cache.set(conn, "exa", {"q": "x"}, {"v": 1}, ttl_seconds=60, now=NOW)
    assert api_cache.get(conn, "exa", {"q": "x"}, now=NOW + timedelta(seconds=61)) is None


def test_entry_is_live_until_it_expires(conn):
    api_cache.set(conn, "exa", {"q": "x"}, {"v": 1}, ttl_seconds=60, now=NOW)
    assert api_cache.get(conn, "exa", {"q": "x"}, now=NOW + timedelta(seconds=59)) == {"v": 1}


def test_set_overwrites_existing_entry(conn):
    api_cache.set(conn, "exa", {"q": "x"}, {"v": 1}, now=NOW)
    api_cache.set(conn, "exa", {"q": "x"}, {"v": 2}, now=NOW)
    assert api_cache.get(conn, "exa", {"q": "x"}, now=NOW) == {"v": 2}
    assert conn.execute("SELECT COUNT(*) FROM api_cache").fetchone()[0] == 1


def test_unicode_survives_a_roundtrip(conn):
    # India-first: festival and category names are routinely non-ASCII.
    payload = {"name": "दिवाली", "regions": ["পশ্চিমবঙ্গ"]}
    api_cache.set(conn, "calendarific", {"q": "दिवाली"}, payload, now=NOW)
    assert api_cache.get(conn, "calendarific", {"q": "दिवाली"}, now=NOW) == payload


def test_get_or_fetch_calls_fetcher_on_miss(conn):
    calls = []

    def fetcher():
        calls.append(1)
        return {"fresh": True}

    response, key, was_cached = api_cache.get_or_fetch(
        conn, "exa", {"q": "x"}, fetcher, now=NOW
    )
    assert (response, was_cached, len(calls)) == ({"fresh": True}, False, 1)
    assert key


def test_get_or_fetch_skips_fetcher_on_hit(conn):
    def fetcher():
        raise AssertionError("should not be called when the entry is cached")

    api_cache.set(conn, "exa", {"q": "x"}, {"cached": True}, now=NOW)
    response, _, was_cached = api_cache.get_or_fetch(
        conn, "exa", {"q": "x"}, fetcher, now=NOW
    )
    assert (response, was_cached) == ({"cached": True}, True)


def test_get_or_fetch_refetches_once_expired(conn):
    api_cache.set(conn, "exa", {"q": "x"}, {"v": "old"}, ttl_seconds=60, now=NOW)
    response, _, was_cached = api_cache.get_or_fetch(
        conn, "exa", {"q": "x"}, lambda: {"v": "new"}, now=NOW + timedelta(seconds=61)
    )
    assert (response, was_cached) == ({"v": "new"}, False)


def test_get_or_fetch_returns_the_provenance_key(conn):
    _, key, _ = api_cache.get_or_fetch(conn, "exa", {"q": "x"}, lambda: {"v": 1}, now=NOW)
    assert key == api_cache.make_key("exa", {"q": "x"})


def test_purge_expired_removes_only_expired_rows(conn):
    api_cache.set(conn, "exa", {"q": "stale"}, {"v": 1}, ttl_seconds=60, now=NOW)
    api_cache.set(conn, "exa", {"q": "fresh"}, {"v": 2}, ttl_seconds=3600, now=NOW)
    api_cache.set(conn, "exa", {"q": "forever"}, {"v": 3}, now=NOW)

    removed = api_cache.purge_expired(conn, now=NOW + timedelta(seconds=61))

    assert removed == 1
    remaining = {row["key"] for row in conn.execute("SELECT key FROM api_cache")}
    assert api_cache.make_key("exa", {"q": "stale"}) not in remaining
    assert len(remaining) == 2
