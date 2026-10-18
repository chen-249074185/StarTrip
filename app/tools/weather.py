"""天气工具。

高德 `maps_weather` 已覆盖逐日天气；此处封装为独立入口，
后续若接心知天气（seniverse）可在此切换数据源。
"""

from __future__ import annotations

from app.tools.amap import call_amap


async def get_weather(city: str) -> list[str]:
    """返回指定城市的天气信息（文本列表）。"""
    return await call_amap("maps_weather", {"city": city})
