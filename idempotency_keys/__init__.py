"""idempotency-keys: run an operation at most once per idempotency key.

A small, framework-agnostic helper that stops retried requests from causing
duplicate side effects. Bring your own store (an in-memory one ships by
default, Redis is one import away) and wrap the work in ``Idempotency.run``.
"""

from __future__ import annotations

from .manager import DEFAULT_TTL_SECONDS, Idempotency, IdempotencyConflict
from .redis_store import RedisStore
from .store import DONE, PENDING, IdempotencyStore, MemoryStore, Record

__all__ = [
    "Idempotency",
    "IdempotencyConflict",
    "DEFAULT_TTL_SECONDS",
    "MemoryStore",
    "RedisStore",
    "IdempotencyStore",
    "Record",
    "PENDING",
    "DONE",
]
