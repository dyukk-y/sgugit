"""Резервные копии: JSON-дамп всех таблиц, сжатый gzip. Работает для SQLite и PostgreSQL."""
from __future__ import annotations

import glob
import gzip
import json
import os
import time
from datetime import datetime

from app.db.repo import Repo
from app.timeutil import tz


async def make_backup(repo: Repo) -> tuple[str, bytes]:
    data = await repo.dump()
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    name = f"backup-{datetime.now(tz()).strftime('%Y%m%d-%H%M')}.json.gz"
    return name, gzip.compress(raw, 6)


def parse_backup(blob: bytes) -> dict:
    try:
        raw = gzip.decompress(blob) if blob[:2] == b"\x1f\x8b" else blob
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise ValueError("Файл не похож на бэкап бота.") from e
    if not isinstance(data, dict) or data.get("format") != 1 or not isinstance(data.get("tables"), dict):
        raise ValueError("Неизвестный формат бэкапа.")
    return data


def save_local(directory: str, name: str, blob: bytes, keep: int = 7) -> None:
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, name), "wb") as f:
        f.write(blob)
    files = sorted(glob.glob(os.path.join(directory, "backup-*.json.gz")), key=os.path.getmtime)
    for old in files[:-keep]:
        try:
            os.remove(old)
        except OSError:
            pass
