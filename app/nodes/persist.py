"""收尾落库：把最终行程写入 trips 表。

- 只在有 trip_plan + score 时写；闲聊/推荐直接跳过
- 写失败只记录，不影响已经生成的回复（DB 是旁路，不是主链路）
"""

from __future__ import annotations

from app.config import settings
from app.db.trips import save_trip
from app.state import TripState


def _title(state: TripState) -> str:
    plan = state.get("trip_plan") or {}
    city = state.get("city") or ""
    days = len(plan.get("days") or [])
    if city and days:
        return f"{city}{days}日游"
    return (state.get("user_input") or "旅行行程")[:50]


async def persist(state: TripState) -> dict:
    if not settings.trip_persist_enabled:
        return {}
    plan = state.get("trip_plan")
    score = state.get("score")
    session_id = state.get("session_id") or ""
    if not plan or score is None or not session_id:
        return {}
    try:
        trip_id = await save_trip(session_id, _title(state), plan, float(score))
        return {"trip_id": trip_id}
    except Exception as e:  # noqa: BLE001
        print(f"[persist] 行程落库失败: {e}")
        return {}
