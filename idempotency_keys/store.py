"""Storage backends for idempotency records.

A store maps an idempotency key to a :class:`Record` that is either *pending*
(an operation is running right now) or *done* (the result is cached). The
manager only needs four operations, and they must be atomic enough that two
requests racing on the same key cannot both start the work.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable

PENDING = "pending"
DONE = "done"


@dataclass
class Record:
    """A stored idempotency record.

    ``state`` is :data:`PENDING` while the operation runs and :data:`DONE`
    once its result is cached. ``value`` holds the cached result and is only
    meaningful when ``state == DONE``.
    """

    state: str
    value: Any = None


@runtime_checkable
class IdempotencyStore(Protocol):
    """The backend contract the manager depends on.

    Any object with these four methods works, which is what keeps the manager
    framework- and infrastructure-agnostic.
    """

    def get(self, key: str) -> Optional[Record]: ...

    def add_pending(self, key: str, ttl_seconds: int) -> bool:
        """Atomically insert a PENDING record. Return ``False`` if the key
        already exists (someone else got there first)."""

    def complete(self, key: str, value: Any, ttl_seconds: int) -> None: ...

    def delete(self, key: str) -> None: ...


class MemoryStore:
    """Thread-safe in-memory store with per-key TTL.

    The default backend. Good for a single process and for tests. TTL is
    tracked with a monotonic clock so it is immune to wall-clock adjustments,
    and expired records are treated as absent (and cleaned up lazily on
    access) so the dict cannot grow without bound for keys that stop being
    queried.
    """

    def __init__(self) -> None:
        self._data: dict[str, tuple[Record, float]] = {}
        self._lock = threading.Lock()

    def _live(self, key: str, now: float) -> Optional[Record]:
        entry = self._data.get(key)
        if entry is None:
            return None
        record, expires_at = entry
        if expires_at <= now:
            del self._data[key]
            return None
        return record

    def get(self, key: str) -> Optional[Record]:
        now = time.monotonic()
        with self._lock:
            record = self._live(key, now)
            # Return a copy so callers can't mutate stored state in place.
            return Record(record.state, record.value) if record else None

    def add_pending(self, key: str, ttl_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            if self._live(key, now) is not None:
                return False
            self._data[key] = (Record(PENDING), now + _floor_ttl(ttl_seconds))
            return True

    def complete(self, key: str, value: Any, ttl_seconds: int) -> None:
        now = time.monotonic()
        with self._lock:
            self._data[key] = (Record(DONE, value), now + _floor_ttl(ttl_seconds))

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)


def _floor_ttl(ttl_seconds: int) -> int:
    """TTL floored at 1 second (0 or negative would expire immediately)."""
    return max(1, int(ttl_seconds))
