"""行程结构归一化。

LLM 输出不可信：`days` / `spots` 可能是字符串、缺字段或混入非法项。
这里在落库和返回前端之前统一成固定结构，避免 `jsonb_array_length` 之类
的查询因脏数据报错，也避免前端渲染崩溃。
"""

from __future__ import annotations

from typing import Any


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def normalize_plan(plan: Any) -> dict:
    """归一化为 {"days": [{"date": "D1", "spots": [{"name": "..."}]}]}。

    - 非 dict / days 非 list → 空行程
    - 非 dict 的 day / spot 丢弃
    - spot 为字符串时视为 {"name": 字符串}
    - 没有有效景点的 day 丢弃
    """
    if not isinstance(plan, dict):
        return {"days": []}

    raw_days = plan.get("days")
    if not isinstance(raw_days, list):
        return {"days": []}

    days: list[dict] = []
    for index, raw_day in enumerate(raw_days, 1):
        if not isinstance(raw_day, dict):
            continue

        raw_spots = raw_day.get("spots")
        if not isinstance(raw_spots, list):
            raw_spots = []

        spots: list[dict] = []
        for raw_spot in raw_spots:
            if isinstance(raw_spot, str):
                raw_spot = {"name": raw_spot}
            if not isinstance(raw_spot, dict):
                continue
            name = _text(raw_spot.get("name"))
            if not name:
                continue
            spot = dict(raw_spot)
            spot["name"] = name
            spots.append(spot)

        if not spots:
            continue

        day = dict(raw_day)
        day["date"] = _text(raw_day.get("date"), f"D{index}")
        day["spots"] = spots
        days.append(day)

    out = dict(plan)
    out["days"] = days
    return out


def plan_is_usable(plan: Any) -> bool:
    """至少有一天包含至少一个有效景点，才允许落库/展示。"""
    return bool(normalize_plan(plan)["days"])
