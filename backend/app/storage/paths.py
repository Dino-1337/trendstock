"""Single source of truth for on-disk locations under backend/data.

Before this module, seven modules each re-derived the data root from their own
depth - and inconsistently: some as ``parents[3] / "backend" / "data"``, others
as ``parents[2] / "data"``. Both happen to resolve to the same directory, which
is exactly why the drift went unnoticed; a module moving one level in the
package tree would have broken silently.

Modules keep their own module-level constants (tests monkeypatch several of
them by name), but those constants are now derived from here rather than
recomputed from scratch.
"""

from pathlib import Path

# app/storage/paths.py -> app/storage -> app -> backend
BACKEND_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = BACKEND_DIR / "data"

RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
FIXTURES_DIR = DATA_DIR / "fixtures"
UPLOADS_DIR = DATA_DIR / "uploads"
VOCAB_DIR = DATA_DIR / "vocabulary"
CACHE_DIR = DATA_DIR / "cache"
TAG_CACHE_DIR = CACHE_DIR / "tags"
TRENDSPYG_DOWNLOAD_DIR = DATA_DIR / ".trendspyg_downloads"

# SQLite lives beside the flat files rather than replacing them: raw daily
# snapshots stay append-only JSON, while derived knowledge, API response caches
# and provenance move into a queryable store.
DB_PATH = DATA_DIR / "trendstock.db"
