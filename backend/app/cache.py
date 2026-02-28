from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any


@dataclass
class CacheEntry:
    value: Any
    expires_at: datetime
    created_at: datetime


class TTLCache:
    def __init__(self):
        self._store: dict[str, CacheEntry] = {}
        self._lock = Lock()

    def get(self, key: str):
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            if entry.expires_at < datetime.now(timezone.utc):
                del self._store[key]
                return None
            return entry

    def set(self, key: str, value: Any, ttl_seconds: int):
        now = datetime.now(timezone.utc)
        with self._lock:
            self._store[key] = CacheEntry(value=value, created_at=now, expires_at=now + timedelta(seconds=ttl_seconds))


cache = TTLCache()
