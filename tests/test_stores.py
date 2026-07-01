"""Tests for the MemoryStore TTL behavior and the RedisStore against a fake."""

from __future__ import annotations

import time

from idempotency_keys import Idempotency, MemoryStore, RedisStore
from idempotency_keys.store import DONE


def test_memory_store_expires_records(monkeypatch):
    store = MemoryStore()
    clock = {"t": 1000.0}
    monkeypatch.setattr("idempotency_keys.store.time.monotonic", lambda: clock["t"])

    store.complete("k", "value", ttl_seconds=10)
    assert store.get("k").value == "value"

    clock["t"] += 11  # advance past the TTL
    assert store.get("k") is None


class FakeRedis:
    """Minimal Redis stand-in supporting get / set(nx, ex) / delete."""

    def __init__(self):
        self.data: dict[str, str] = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def delete(self, key):
        self.data.pop(key, None)


def test_redis_store_round_trip():
    store = RedisStore(FakeRedis())
    assert store.get("k") is None
    assert store.add_pending("k", 60) is True
    # A second claim on the same key fails (NX semantics).
    assert store.add_pending("k", 60) is False
    store.complete("k", {"id": 7}, 60)
    record = store.get("k")
    assert record.state == DONE
    assert record.value == {"id": 7}


def test_redis_store_prefixes_keys():
    fake = FakeRedis()
    store = RedisStore(fake, prefix="myapp")
    store.add_pending("abc", 60)
    assert "myapp:abc" in fake.data


def test_manager_works_with_redis_store():
    idem = Idempotency(RedisStore(FakeRedis()))
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        return "result"

    assert idem.run("k", op) == "result"
    assert idem.run("k", op) == "result"
    assert calls["n"] == 1
