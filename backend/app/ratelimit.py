"""Per-instance token-bucket rate limiting.

This is a second line of defence. The first is the edge WAF rate rule (infra/terraform).
Because buckets are per process, the effective limit scales with replica count; this is
documented in docs/operations/abuse-controls.md.
"""

from __future__ import annotations

import threading
import time

from fastapi import HTTPException, Request, status


class TokenBucket:
    def __init__(self, rate_per_minute: int, burst: int | None = None) -> None:
        self.rate = rate_per_minute / 60.0
        self.capacity = float(burst or rate_per_minute)
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, cost: float = 1.0) -> tuple[bool, float]:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= cost:
                self._state[key] = (tokens - cost, now)
                return True, 0.0
            self._state[key] = (tokens, now)
            if len(self._state) > 100_000:  # bound memory
                self._state.clear()
            return False, (cost - tokens) / self.rate


def client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
    return ip


def enforce(bucket: TokenBucket, key: str) -> None:
    ok, retry = bucket.allow(key)
    if not ok:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded",
                            headers={"Retry-After": str(max(1, int(retry + 0.5)))})
