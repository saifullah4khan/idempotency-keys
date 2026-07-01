# idempotency-keys

Run an operation at most once per idempotency key, so retried requests stop
causing duplicate side effects.

## The problem

A client sends "charge this card" or "create this order," the network drops
before the response comes back, and now nobody knows if it worked. If the
client retries, you risk charging twice. If it doesn't, the request might be
lost. The accepted fix is an idempotency key: the client attaches a unique
value to the request, and the server promises to run the work only once for
that value, returning the original result on any replay.

The subtlety that trips people up is the in-flight case. Two copies of the
same request can arrive within milliseconds of each other, before the first
has finished. Deduping only on completed results lets both start the work.
This library handles that case explicitly.

## Quickstart

```bash
pip install idempotency-keys
```

```python
from idempotency_keys import Idempotency, IdempotencyConflict

idem = Idempotency()  # in-memory store by default

def charge_card():
    return {"charge_id": "ch_123"}

# First call runs charge_card(); any later call with the same key returns
# the cached result without running it again.
result = idem.run("client-supplied-key", charge_card)
```

In a web handler, translate a conflict into an HTTP 409:

```python
try:
    result = idem.run(request.headers["Idempotency-Key"], charge_card)
except IdempotencyConflict:
    return {"error": "request already in progress"}, 409
```

## Sharing state across processes

The default `MemoryStore` is per-process. To dedupe across workers or hosts,
pass a Redis-backed store. There is no hard dependency on `redis`; you hand in
a client you already have.

```python
import redis
from idempotency_keys import Idempotency, RedisStore

idem = Idempotency(RedisStore(redis.from_url("redis://localhost:6379")))
```

Any object with `get`, `set(key, value, nx=..., ex=...)`, and `delete` works,
which also makes the store trivial to fake in tests.

## Design decisions

**The in-flight case is a first-class outcome.** Claiming a key uses an atomic
insert (a locked dict in memory, `SET NX EX` in Redis), so exactly one caller
wins the race and starts the work. A second caller that finds the key still
pending gets an `IdempotencyConflict`, which maps cleanly onto HTTP 409. This
is the part that makes the helper safe under real concurrency rather than only
on sequential retries.

**Failures are never cached.** If the wrapped operation raises, the pending
marker is released and the exception propagates. A transient downstream error
must not poison the key so that every future retry replays the failure; the
next attempt with the same key gets a fresh run.

**The store is a small protocol, not a hard dependency.** The manager needs
only four methods, so it stays framework- and infrastructure-agnostic. Memory
for a single process and tests, Redis for a fleet, and anything else you
implement against the same four methods.

**TTL uses a monotonic clock in memory.** Expiry is measured with
`time.monotonic`, so a wall-clock adjustment can't make a record live forever
or expire early, and expired keys are cleaned up lazily on access so the map
stays bounded.

**Only the key scopes the cache.** Keeping the surface minimal, the key you
pass is the whole identity. If you are multi-tenant, namespace the key
yourself (for example `f"{tenant_id}:{client_key}"`) or use the Redis store's
`prefix`.

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `Idempotency(ttl_seconds=...)` | `86400` (1 day) | How long a completed result stays replayable. |
| `RedisStore(prefix=...)` | `"idem"` | Key namespace inside Redis. |

## Testing

```bash
pip install -e ".[dev]"
pytest
```

The suite covers the run-once and cache-hit paths, the in-flight conflict, key
release on failure, TTL expiry with a faked clock, and the Redis store driven
through an in-memory fake so no server is required.

## License

MIT. See [LICENSE](LICENSE).
