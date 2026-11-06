"""高德 amap-maps 工具集（经 MCP 客户端调用）。

惰性连接：首次调用时建立 MCP 会话并复用；连接失败由上层（executor）降级处理。
冷启动：应用启动时调用 warm_up_amap() 预连接，避免第一个用户请求撞上
`npx` 启动 + 所有并发任务堵在同一把锁上的超时。
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
    """惰性建立并复用 MCP 会话（加锁防并发重复连接）；会话断开时自动重连。"""
    global _client
    async with _lock:
        if _client is not None and not _client.alive:
            try:
                await _client.close()
            except Exception as e:  # noqa: BLE001
                print(f"[amap] 关闭失效 MCP 会话失败: {e}")
            _client = None
        if _client is None:
            client = MCPClient(
                amap_server_params(settings.amap_key),
                call_timeout=settings.tool_timeout,
            )
            try:
                await asyncio.wait_for(
                    client.start(), timeout=settings.mcp_connect_timeout
                )
            except Exception:
                await client.close()
                raise
            _client = client
        return _client


async def call_amap(name: str, args: dict) -> list[str]:
    if name not in AMAP_TOOLS:
        raise ValueError(f"未知的高德工具: {name}")
    client = await _client_or_connect()
    return await client.call(name, args)


async def warm_up_amap() -> None:
    """启动期预热：失败只记日志，不影响 Web 服务启动。"""
    if not settings.amap_key:
        print("[amap] 未配置 AMAP_KEY，跳过预热")
        return
    try:
        await _client_or_connect()
        print("[amap] MCP 预热成功")
    except Exception as e:  # noqa: BLE001
        print(f"[amap] MCP 预热失败（首次调用时会重试）: {e}")


def amap_ready() -> bool:
    return _client is not None and _client.alive


async def close_amap() -> None:
    """关闭 MCP 会话（应用关闭时调用）。"""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
