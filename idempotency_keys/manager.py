"""The idempotency manager: run an operation at most once per key.

The manager coordinates a store so that a repeated request with the same
idempotency key returns the original result instead of doing the work twice,
and so that a request arriving while the first is still in flight is rejected
rather than allowed to run in parallel.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from .store import DONE, IdempotencyStore, MemoryStore

T = TypeVar("T")

# One day. Long enough to cover any realistic client retry window, short
# enough that keys don't accumulate forever.
DEFAULT_TTL_SECONDS = 86_400


class IdempotencyConflict(Exception):
    """Raised when a request arrives for a key whose operation is still running.

    This is the signal to return an HTTP 409 Conflict: the first request holds
    the key and has not finished, so the safe answer is "try again shortly"
    rather than starting the work a second time.
    """

    def __init__(self, key: str) -> None:
        super().__init__(f"An operation for key {key!r} is already in progress.")
        self.key = key


class Idempotency:
    """Wrap operations so each idempotency key runs at most once.

    :param store: Any :class:`~idempotency_keys.store.IdempotencyStore`.
        Defaults to an in-process :class:`~idempotency_keys.store.MemoryStore`.
    :param ttl_seconds: How long a completed result stays replayable.
    """

    def __init__(
        self,
        store: IdempotencyStore | None = None,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.store = store or MemoryStore()
        self.ttl_seconds = ttl_seconds

    def run(self, key: str, operation: Callable[[], T]) -> T:
        """Return the result of *operation*, running it at most once per *key*.

        On a cache hit the stored result is returned and *operation* is not
        called. If another caller holds the key and is still running, raises
        :class:`IdempotencyConflict`.

        If *operation* raises, the pending marker is cleared so the caller can
        retry with the same key. Only successful results are cached, which
        avoids poisoning a key with a transient failure.
        """
        if not key:
            raise ValueError("An idempotency key is required.")

        existing = self.store.get(key)
        if existing is not None:
            return self._resolve(key, existing)

        # Try to claim the key. add_pending is atomic, so if it returns False
        # another caller claimed it between our get and now.
        if not self.store.add_pending(key, self.ttl_seconds):
            existing = self.store.get(key)
            if existing is not None:
                return self._resolve(key, existing)
            # The winner finished and its record already expired; treat as a
            # conflict rather than racing again.
            raise IdempotencyConflict(key)

        try:
            result = operation()
        except Exception:
            # Release the key so a retry is possible; do not cache failures.
            self.store.delete(key)
            raise

        self.store.complete(key, result, self.ttl_seconds)
        return result

    def _resolve(self, key: str, record) -> Any:
        if record.state == DONE:
            return record.value
        raise IdempotencyConflict(key)
