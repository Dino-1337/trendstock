"""Disk-persisted tag cache, keyed by content hash. A trend or product already
tagged should not be re-sent to Groq on the next pipeline run - this matters
more than raw speed, since it's what keeps real usage far under the free
tier's daily/per-minute limits.

Keyed on (text, vocabulary version) so a vocabulary update (new categories.json)
invalidates stale entries automatically instead of silently reusing tags
selected from a vocabulary that no longer exists.
"""

import hashlib
import json
from pathlib import Path

from app.storage.paths import TAG_CACHE_DIR
from app.tagging.base import TagResult

CACHE_DIR = TAG_CACHE_DIR


class TagCache:
    def __init__(self, namespace, vocabulary_version, cache_dir=CACHE_DIR):
        self.path = Path(cache_dir) / f"{namespace}.json"
        self._vocabulary_version = vocabulary_version
        self._entries = {}
        self._dirty = False
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if raw.get("vocabulary_version") == self._vocabulary_version:
            self._entries = raw.get("entries", {})
        # else: vocabulary changed since this cache was written; start fresh
        # rather than risk serving tags selected from a stale term list.

    @staticmethod
    def _key(text):
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

    def get(self, text):
        entry = self._entries.get(self._key(text))
        if entry is None:
            return None
        return TagResult(tags=entry["tags"], source=entry["source"], detail=entry.get("detail", []))

    def set(self, text, result):
        self._entries[self._key(text)] = {
            "tags": result.tags,
            "source": result.source,
            "detail": result.detail,
        }
        self._dirty = True

    def clear(self):
        """Drop every cached entry and remove the file. Used by the manual
        re-tag action, so a run that fell back to rule-based (Groq rate
        limited) can be retried instead of being cached in forever."""
        self._entries = {}
        self._dirty = False
        self.path.unlink(missing_ok=True)

    def flush(self):
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(
                {"vocabulary_version": self._vocabulary_version, "entries": self._entries},
                f, indent=2, ensure_ascii=False,
            )
        self._dirty = False
