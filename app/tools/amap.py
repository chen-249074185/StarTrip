"""高德 amap-maps 工具集（经 MCP 客户端调用）。

惰性连接：首次调用时建立 MCP 会话并复用；连接失败由上层（executor）降级处理。
"""

from __future__ import annotations

import asyncio

from app.config import settings
from app.mcp.client import MCPClient, amap_server_params

# amap-maps 暴露的工具名（白名单）
AMAP_TOOLS = {
    "maps_text_search",
    "maps_around_search",
    "maps_direction_driving",
    "maps_direction_walking",
    "maps_direction_transit_integrated",
    "maps_distance",
    "maps_weather",
    "maps_geocode",
    "maps_regeocode",
}

_client: MCPClient | None = None
_lock = asyncio.Lock()


async def _client_or_connect() -> MCPClient:
    """惰性建立并复用 MCP 会话（加锁防并发重复连接）。"""
    global _client
    async with _lock:
        if _client is None:
            c = MCPClient(amap_server_params(settings.amap_key))
            await c.start()
            _client = c
        return _client


async def call_amap(name: str, args: dict) -> list[str]:
    if name not in AMAP_TOOLS:
        raise ValueError(f"未知的高德工具: {name}")
    client = await _client_or_connect()
    return await client.call(name, args)


async def close_amap() -> None:
    """关闭 MCP 会话（应用关闭时调用）。"""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
