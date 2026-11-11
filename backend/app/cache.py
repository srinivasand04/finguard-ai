"""Small Redis cache helper. Degrades gracefully (no cache) if Redis is unavailable."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import redis

from app.config import get_settings

log = logging.getLogger(__name__)
_client: redis.Redis | None = None
_disabled = False


def client() -> redis.Redis | None:
    global _client, _disabled
    if _disabled:
        return None
    if _client is None:
        try:
            _client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
            _client.ping()
        except Exception as e:  # pragma: no cover - environment dependent
            log.warning("Redis unavailable, caching disabled: %s", e)
            _client, _disabled = None, True
    return _client


def cached(key: str, producer: Callable[[], Any], ttl: int | None = None) -> Any:
    c = client()
    if c is not None:
        try:
            hit = c.get(key)
            if hit is not None:
                return json.loads(hit)
        except redis.RedisError:
            pass
    value = producer()
    if c is not None:
        try:
            c.setex(key, ttl or get_settings().cache_ttl_seconds, json.dumps(value, default=str))
        except redis.RedisError:
            pass
    return value


def ping() -> bool:
    c = client()
    try:
        return bool(c and c.ping())
    except redis.RedisError:
        return False


def disable_for_tests() -> None:
    global _disabled
    _disabled = True
