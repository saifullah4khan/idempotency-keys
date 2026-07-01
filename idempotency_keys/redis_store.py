"""A Redis-backed store for sharing idempotency state across processes.

This module has no hard dependency on the ``redis`` package. You pass in an
already-constructed client (anything exposing ``get``, ``set`` with ``nx`` and
``ex``, and ``delete``), which keeps this library dependency-light and lets
you point it at ``redis-py``, a cluster client, or a fake in tests.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .store import DONE, PENDING, Record, _floor_ttl


class RedisStore:
    """Store idempotency records in Redis, JSON-encoded, with native TTL.

    The atomic insert relies on Redis ``SET key value NX EX ttl``: it writes
    only when the key is absent and returns a truthy value only for the writer
    that won the race. That is what guarantees exactly one caller starts the
    work even across many processes.
    """

    def __init__(self, client: Any, *, prefix: str = "idem") -> None:
        self._client = client
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    def get(self, key: str) -> Optional[Record]:
        raw = self._client.get(self._key(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            # A malformed entry is treated as absent so one bad value can
            # never wedge a key.
            return None
        state = data.get("state")
        if state not in (PENDING, DONE):
            return None
        return Record(state=state, value=data.get("value"))

    def add_pending(self, key: str, ttl_seconds: int) -> bool:
        payload = json.dumps({"state": PENDING, "value": None})
        result = self._client.set(
            self._key(key), payload, nx=True, ex=_floor_ttl(ttl_seconds)
        )
        return bool(result)

    def complete(self, key: str, value: Any, ttl_seconds: int) -> None:
        payload = json.dumps({"state": DONE, "value": value})
        self._client.set(self._key(key), payload, ex=_floor_ttl(ttl_seconds))

    def delete(self, key: str) -> None:
        self._client.delete(self._key(key))
