"""A rate limit on the demo path only.

Demo mode spends the host's money, so it needs a ceiling: without one, a single
visitor in a loop is an unbounded bill. Bring-your-own-key requests are exempt —
the caller is spending their own budget, and rationing it would be rude.

Deliberately a fixed-window counter in process memory rather than Redis. This is
one container; a second replica would each get their own window, which is a real
limitation and an acceptable one at this scale. The alternative is a dependency
that exists only to make the demo's cost ceiling exact.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# Generous enough that nobody exploring the demo will notice, small enough that
# a script can't run up a bill.
ASK_PER_HOUR = 30
UPLOAD_PER_HOUR = 10
WINDOW_SECONDS = 3600

_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_key(request: Request) -> str:
    # X-Forwarded-For is set by the platform's proxy; uvicorn runs with
    # --proxy-headers so request.client already reflects it, but the header is
    # checked first for hosts that don't rewrite.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce(request: Request, bucket: str, limit: int) -> None:
    """Raise 429 if this client has exhausted `bucket` for the hour."""
    if getattr(request.state, "byok", False):
        return

    key = f"{bucket}:{_client_key(request)}"
    now = time.monotonic()
    hits = _hits[key]
    while hits and now - hits[0] > WINDOW_SECONDS:
        hits.popleft()

    if len(hits) >= limit:
        retry_after = int(WINDOW_SECONDS - (now - hits[0])) + 1
        raise HTTPException(
            429,
            detail=(
                "The shared demo is rate-limited so it stays free to run. "
                "Add your own API key in settings to continue without limits."
            ),
            headers={"Retry-After": str(retry_after)},
        )
    hits.append(now)


def reset() -> None:
    """Test hook."""
    _hits.clear()
