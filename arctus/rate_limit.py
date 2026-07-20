"""Per-session rolling 60-second rate limiting.

In-memory (not persisted) — this is enforcement, not history. If you want
durable quota accounting, wire it into the session store.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict


@dataclass
class RateLimitConfig:
    max_requests_per_minute: int = 30
    max_tokens_per_minute: int = 250_000
    enforce_strict_quota: bool = True


class RateLimitError(RuntimeError):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason  # "requests" | "tokens"
        self.detail = detail


_BUCKETS: Dict[str, dict] = {}


def check_and_update(
    session_id: str,
    config: RateLimitConfig,
    estimated_tokens: int = 1000,
) -> None:
    """Rolling 60s window. Raises RateLimitError if the quota is exceeded."""
    now = time.time()
    bucket = _BUCKETS.get(session_id)
    if not bucket or now - bucket["window_start"] > 60:
        bucket = {"tokens": 0, "requests": 0, "window_start": now}

    if config.enforce_strict_quota:
        if bucket["requests"] >= config.max_requests_per_minute:
            raise RateLimitError(
                "requests",
                f"Rate limit exceeded: Max {config.max_requests_per_minute} requests/min reached.",
            )
        if bucket["tokens"] + estimated_tokens > config.max_tokens_per_minute:
            raise RateLimitError(
                "tokens",
                f"Token rate limit exceeded: Max {config.max_tokens_per_minute} tokens/min reached.",
            )

    bucket["requests"] += 1
    bucket["tokens"] += estimated_tokens
    _BUCKETS[session_id] = bucket


def clear(session_id: str) -> None:
    _BUCKETS.pop(session_id, None)


def estimate_tokens(text: str) -> int:
    """Rough heuristic: ~4 chars/token. Good enough for pre-flight checks."""
    return max(1, len(text) // 4)
