"""Fixed-window failure rate limiting for authentication endpoints.

Uses Redis when reachable so limits survive process restarts and are shared
across workers; falls back to an in-process counter if Redis is unavailable
so protection never silently disappears.
"""

from __future__ import annotations

import threading
import time

from redis import Redis

from app.config import get_settings

_PREFIX = "leadintel:ratelimit:"
_local_lock = threading.Lock()
_local_counters: dict[str, tuple[int, float]] = {}


def _redis_client() -> Redis | None:
    try:
        client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
        client.ping()
        return client
    except Exception:
        return None


def _local_increment(key: str, window_seconds: int) -> int:
    now = time.monotonic()
    with _local_lock:
        count, expires = _local_counters.get(key, (0, 0.0))
        if now >= expires:
            count, expires = 0, now + window_seconds
        count += 1
        _local_counters[key] = (count, expires)
        return count


def _local_count(key: str) -> int:
    now = time.monotonic()
    with _local_lock:
        count, expires = _local_counters.get(key, (0, 0.0))
        return count if now < expires else 0


def register_failure(key: str, window_seconds: int | None = None) -> None:
    window = window_seconds or get_settings().login_window_seconds
    client = _redis_client()
    if client is not None:
        try:
            redis_key = _PREFIX + key
            count = client.incr(redis_key)
            if count == 1:
                client.expire(redis_key, window)
            return
        except Exception:
            pass
    _local_increment(key, window)


def too_many_failures(key: str, limit: int | None = None) -> bool:
    max_failures = limit if limit is not None else get_settings().login_max_failures
    client = _redis_client()
    if client is not None:
        try:
            value = client.get(_PREFIX + key)
            return int(value or 0) >= max_failures
        except Exception:
            pass
    return _local_count(key) >= max_failures


def clear_failures(key: str) -> None:
    client = _redis_client()
    if client is not None:
        try:
            client.delete(_PREFIX + key)
        except Exception:
            pass
    with _local_lock:
        _local_counters.pop(key, None)
