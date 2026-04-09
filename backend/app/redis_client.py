from typing import Any

import redis

from app.config import get_settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis | None:
    global _client
    if _client is not None:
        return _client
    try:
        r = redis.from_url(get_settings().redis_url, decode_responses=True)
        r.ping()
        _client = r
    except (redis.RedisError, OSError):
        _client = None
    return _client


def redis_ok() -> dict[str, Any]:
    r = get_redis()
    if r is None:
        return {"redis": "unavailable"}
    try:
        r.ping()
        return {"redis": "ok"}
    except redis.RedisError:
        return {"redis": "error"}
