"""Disk-persisted tag cache (app/tagging/cache.py). Uses tmp_path so tests
never touch the real data/cache/tags/ directory."""

from app.tagging.base import TagResult
from app.tagging.cache import TagCache


def test_set_then_get_round_trips(tmp_path):
    cache = TagCache("products", "v1", cache_dir=tmp_path)
    result = TagResult(tags=["Sneakers"], source="rule_based", detail=[{"tag": "Sneakers"}])
    cache.set("nike sneakers text", result)
    cache.flush()

    reloaded = TagCache("products", "v1", cache_dir=tmp_path)
    got = reloaded.get("nike sneakers text")
    assert got is not None
    assert got.tags == ["Sneakers"]
    assert got.source == "rule_based"


def test_miss_returns_none(tmp_path):
    cache = TagCache("products", "v1", cache_dir=tmp_path)
    assert cache.get("never seen this text") is None


def test_vocabulary_version_change_invalidates_cache(tmp_path):
    """A vocabulary update must not silently keep serving tags selected from
    a term list that no longer exists."""
    cache_v1 = TagCache("products", "v1", cache_dir=tmp_path)
    cache_v1.set("nike sneakers", TagResult(tags=["Sneakers"], source="rule_based"))
    cache_v1.flush()

    cache_v2 = TagCache("products", "v2", cache_dir=tmp_path)
    assert cache_v2.get("nike sneakers") is None


def test_flush_without_changes_does_not_write_file(tmp_path):
    cache = TagCache("products", "v1", cache_dir=tmp_path)
    cache.flush()
    assert not cache.path.exists()


def test_different_namespaces_do_not_collide(tmp_path):
    products_cache = TagCache("products", "v1", cache_dir=tmp_path)
    trends_cache = TagCache("trends", "v1", cache_dir=tmp_path)
    products_cache.set("shared text", TagResult(tags=["Sneakers"], source="rule_based"))
    products_cache.flush()
    assert trends_cache.get("shared text") is None
