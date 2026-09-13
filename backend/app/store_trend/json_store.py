from datetime import date
import json

from app.storage.paths import RAW_DATA_DIR


def store_trend_data(source, data):
    today = date.today()
    dir_path = RAW_DATA_DIR / str(today)
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / f"{source}.json"
    # Explicit utf-8 + ensure_ascii=False: trend titles are heavily Devanagari,
    # Bengali and Telugu, and the India-first event work adds more. This used to
    # survive only because json.dump escapes non-ASCII by default.
    with open(file_path, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file, indent=2, default=str, ensure_ascii=False)
    return file_path
