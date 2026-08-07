"""Demo-path rate limiting.

The property that matters: a visitor spending their own key is never rationed,
and a visitor spending the host's is.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import limits


class _Request:
    """Minimal stand-in — enforce() only reads headers, client, and state."""

    def __init__(self, ip: str = "1.2.3.4", byok: bool = False):
        self.headers = {}
        self.client = type("C", (), {"host": ip})()
        self.state = type("S", (), {"byok": byok})()


@pytest.fixture(autouse=True)
def _clean():
    limits.reset()
    yield
    limits.reset()


def test_demo_requests_are_capped():
    request = _Request()
    for _ in range(limits.ASK_PER_HOUR):
        limits.enforce(request, "ask", limits.ASK_PER_HOUR)
    with pytest.raises(HTTPException) as exc:
        limits.enforce(request, "ask", limits.ASK_PER_HOUR)
    assert exc.value.status_code == 429
    assert "your own API key" in exc.value.detail


def test_byok_requests_are_never_capped():
    """They're spending their own money — rationing it would be rude."""
    request = _Request(byok=True)
    for _ in range(limits.ASK_PER_HOUR * 3):
        limits.enforce(request, "ask", limits.ASK_PER_HOUR)


def test_clients_are_counted_separately():
    a, b = _Request("10.0.0.1"), _Request("10.0.0.2")
    for _ in range(limits.ASK_PER_HOUR):
        limits.enforce(a, "ask", limits.ASK_PER_HOUR)
    limits.enforce(b, "ask", limits.ASK_PER_HOUR)  # unaffected


def test_buckets_are_independent():
    """Asking a lot shouldn't block uploading."""
    request = _Request()
    for _ in range(limits.ASK_PER_HOUR):
        limits.enforce(request, "ask", limits.ASK_PER_HOUR)
    limits.enforce(request, "upload", limits.UPLOAD_PER_HOUR)


def test_forwarded_for_identifies_the_client_behind_a_proxy():
    a = _Request("10.0.0.1")
    a.headers = {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}
    b = _Request("10.0.0.1")
    b.headers = {"x-forwarded-for": "203.0.113.10, 10.0.0.1"}
    for _ in range(limits.ASK_PER_HOUR):
        limits.enforce(a, "ask", limits.ASK_PER_HOUR)
    limits.enforce(b, "ask", limits.ASK_PER_HOUR)  # different real client
