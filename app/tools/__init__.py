"""工具注册表：tool 名 → 异步处理函数。

executor 按 plan 里的 `tool` 名从注册表取函数调用，实现"工具名与实现解耦"。
"""

from __future__ import annotations

from functools import partial
from typing import Any, Awaitable, Callable

from app.tools.amap import AMAP_TOOLS, call_amap, close_amap
from app.tools.weather import get_weather

ToolFn = Callable[[dict], Awaitable[Any]]

REGISTRY: dict[str, ToolFn] = {}


def register(name: str, fn: ToolFn) -> None:
    REGISTRY[name] = fn


def get_tool(name: str) -> ToolFn | None:
    return REGISTRY.get(name)


def all_tool_names() -> list[str]:
    return sorted(REGISTRY)


# 注册高德工具（tool 名即 MCP 远程工具名）
for _name in AMAP_TOOLS:
    register(_name, partial(call_amap, _name))

# 天气别名
register("weather", lambda args: get_weather(args.get("city", "")))

__all__ = ["REGISTRY", "register", "get_tool", "all_tool_names", "close_amap"]
