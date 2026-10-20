"""Redis 客户端（偏好 / 缓存）。连接失败时降级，不阻断主流程。"""

from __future__ import annotations

import redis.asyncio as redis

from app.config import settings

_client: redis.Redis | None = None


async def init_redis() -> redis.Redis | None:
    global _client
    try:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        _client = client
        return client
    except Exception as e:  # noqa: BLE001
        print(f"[startup] Redis 未就绪，偏好功能降级: {e}")
        _client = None
        return None


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_redis() -> redis.Redis | None:
    return _client


def redis_ready() -> bool:
    return _client is not None
