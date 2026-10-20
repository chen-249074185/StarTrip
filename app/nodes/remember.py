"""收尾节点：把本轮助手回复与行程摘要写入历史（只记一次）。"""

from __future__ import annotations

from typing import Any

from app.memory import append_message
from app.state import TripState


def _plan_digest(plan: dict[str, Any]) -> str:
    """把行程压成一句摘要，供下一轮规划参考。"""
    parts: list[str] = []
    for day in plan.get("days") or []:
        names = [
            spot.get("name")
            for spot in day.get("spots") or []
            if spot.get("name")
        ]
        if names:
            parts.append(f"{day.get('date') or ''}: {'、'.join(names)}")
    return "；".join(parts)


async def remember(state: TripState) -> dict:
    reply = (state.get("reply") or "").strip()
    digest = _plan_digest(state.get("trip_plan") or {})
    if digest:
        content = f"{reply}\n行程安排：{digest}" if reply else f"行程安排：{digest}"
    else:
        content = reply
    history = append_message(state.get("history") or [], "assistant", content)
    return {"history": history}
