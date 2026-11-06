"""收尾落库：把最终行程写入 trips 表。

- 只在有 trip_plan + score 时写；闲聊/推荐/取消直接跳过
- 确定性校验不通过、或景点大量无依据 → 不落库（避免把不可行/幻觉行程当成功结果）
- 写失败只记录，不影响已经生成的回复（DB 是旁路，不是主链路）
"""

from __future__ import annotations

from app.config import settings
from app.db.trips import save_trip
from app.plan import normalize_plan, plan_is_usable
from app.state import TripState


def _title(state: TripState, plan: dict) -> str:
    city = state.get("city") or ""
    days = len(plan.get("days") or [])
    if city and days:
        return f"{city}{days}日游"
    return (state.get("user_input") or "旅行行程")[:50]


async def persist(state: TripState) -> dict:
    if not settings.trip_persist_enabled or state.get("cancelled"):
        return {}
    plan = normalize_plan(state.get("trip_plan"))
    score = state.get("score")
    session_id = state.get("session_id") or ""
    validation = state.get("validation") or {}
    grounding = state.get("grounding") or {}
    if not plan_is_usable(plan) or score is None or not session_id:
        return {}
    if validation and not validation.get("ok", True):
        return {}   # 确定性校验不通过：不落库，避免把不可行行程当成功结果
    if grounding and not grounding.get("applicable", True):
        return {}   # 没有外部证据：不落库，避免把未验证行程当成功结果
    if (
        grounding.get("applicable")
        and grounding.get("ratio", 0.0) > settings.grounding_max_ungrounded_ratio
    ):
        return {}   # 大部分景点无证据：不把幻觉行程落库
    try:
        trip_id = await save_trip(
            session_id,
            _title(state, plan),
            plan,
            float(score),
            status="ok",
            validation=validation or None,
            grounding=grounding or None,
        )
        return {"trip_id": trip_id}
    except Exception as e:  # noqa: BLE001
        print(f"[persist] 行程落库失败: {e}")
        return {}
