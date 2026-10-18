"""MCP 客户端：在独立后台任务中持有会话，跨任务安全调用。

MCP 的 stdio 客户端基于 anyio task group，cancel scope 必须在进入它的同一任务内退出，
不能把 `async with stdio_client(...)` 的退出放到别的任务里。
这里用「专用任务 + 队列」模式：会话生命周期全在 _run() 任务内，调用方通过队列投递请求。
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    """单个 MCP server 的会话封装（后台任务 + 队列）。"""

    def __init__(self, params: StdioServerParameters):
        self._params = params
        self._tools: list[dict] = []
        self._task: asyncio.Task | None = None
        self._inbox: asyncio.Queue | None = None
        self._ready = asyncio.Event()
        self._error: BaseException | None = None

    async def start(self) -> None:
        """启动后台会话任务，等待就绪（或抛出连接错误）。"""
        self._inbox = asyncio.Queue()
        self._ready.clear()
        self._error = None
        self._task = asyncio.create_task(self._run())
        await self._ready.wait()
        if self._error is not None:
            raise self._error

    async def _run(self) -> None:
        try:
            async with stdio_client(self._params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    resp = await session.list_tools()
                    self._tools = [
                        {
                            "name": t.name,
                            "description": t.description,
                            "input_schema": getattr(t, "inputSchema", None),
                        }
                        for t in resp.tools
                    ]
                    self._ready.set()
                    while True:
                        fut, name, args = await self._inbox.get()
                        if name is None:  # 关闭哨兵
                            break
                        try:
                            res = await session.call_tool(name, args)
                            texts = [
                                item.text
                                for item in res.content
                                if getattr(item, "type", None) == "text"
                            ]
                            if not fut.done():
                                fut.set_result(texts)
                        except Exception as e:  # noqa: BLE001
                            if not fut.done():
                                fut.set_exception(e)
        except BaseException as e:  # noqa: BLE001
            self._error = e
            if not self._ready.is_set():
                self._ready.set()

    @property
    def tools(self) -> list[dict]:
        return self._tools

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        """投递一次工具调用，等待后台任务返回结果。"""
        if self._inbox is None:
            raise RuntimeError("MCP client 未 start()")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._inbox.put((fut, name, arguments))
        return await fut

    async def close(self) -> None:
        if self._inbox is not None:
            await self._inbox.put((None, None, None))
        if self._task is not None:
            await self._task
            self._task = None
        self._inbox = None


def amap_server_params(api_key: str) -> StdioServerParameters:
    """高德 amap-maps MCP server 的 stdio 启动参数。"""
    return StdioServerParameters(
        command="npx",
        args=["-y", "@amap/amap-maps-mcp-server"],
        env={"AMAP_MAPS_API_KEY": api_key},
    )
