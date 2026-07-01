"""Tests for the Idempotency manager against the in-memory store."""

from __future__ import annotations

import pytest

from idempotency_keys import Idempotency, IdempotencyConflict, MemoryStore
from idempotency_keys.store import PENDING


def test_operation_runs_once_and_result_is_cached():
    idem = Idempotency(MemoryStore())
    calls = {"n": 0}

    def operation():
        calls["n"] += 1
        return {"charge_id": "ch_123"}

    first = idem.run("key-1", operation)
    second = idem.run("key-1", operation)

    assert first == second == {"charge_id": "ch_123"}
    assert calls["n"] == 1  # the second call was served from cache


def test_different_keys_run_independently():
    idem = Idempotency(MemoryStore())
    assert idem.run("a", lambda: 1) == 1
    assert idem.run("b", lambda: 2) == 2


def test_in_flight_key_raises_conflict():
    store = MemoryStore()
    idem = Idempotency(store)
    # Simulate a request that claimed the key and is still running.
    store.add_pending("key-1", ttl_seconds=60)

    with pytest.raises(IdempotencyConflict) as exc:
        idem.run("key-1", lambda: "should not run")
    assert exc.value.key == "key-1"


def test_failed_operation_releases_the_key():
    idem = Idempotency(MemoryStore())

    def boom():
        raise RuntimeError("downstream failed")

    with pytest.raises(RuntimeError):
        idem.run("key-1", boom)

    # The key was released, so a retry is allowed and can succeed.
    assert idem.run("key-1", lambda: "recovered") == "recovered"


def test_failure_is_not_cached():
    idem = Idempotency(MemoryStore())
    calls = {"n": 0}

    def sometimes():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("transient")
        return "ok"

    with pytest.raises(ValueError):
        idem.run("key-1", sometimes)
    assert idem.run("key-1", sometimes) == "ok"
    assert calls["n"] == 2


def test_empty_key_is_rejected():
    idem = Idempotency(MemoryStore())
    with pytest.raises(ValueError):
        idem.run("", lambda: 1)


def test_pending_state_is_visible_in_store():
    store = MemoryStore()
    assert store.add_pending("k", 60) is True
    assert store.add_pending("k", 60) is False  # already claimed
    record = store.get("k")
    assert record is not None and record.state == PENDING
