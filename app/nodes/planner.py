"""规划节点：需求 → 工具任务清单（LLM 结构化输出）。

- 首次：从 user_input 拆解任务
- 回环：携带 feedback 修正
- LLM 失败/非法 JSON：降级为默认任务
"""

from __future__ import annotations

import json

from app.llm import chat
from app.memory import prior_history
from app.state import TripState

PLANNER_PROMPT = """你是旅行规划任务拆解器。根据用户需求，输出要调用的工具任务清单 JSON：
{"tasks": [{"tool": "<工具名>", "args": {...}}]}

可用工具：
- maps_text_search: 关键词搜景点，args: {"keywords": "...", "city": "..."}
- maps_direction_driving: 驾车路线，args: {"origin": "...", "destination": "...", "city": "..."}
- maps_weather: 城市天气，args: {"city": "..."}

规则：先搜景点，必要时加路线/天气。只输出 JSON，不要解释。"""


def _fallback(user_input: str, city: str = "") -> list[dict]:
    if city:
        return [
            {"tool": "maps_text_search", "args": {"keywords": "必去景点", "city": city}},
            {"tool": "maps_weather", "args": {"city": city}},
        ]
    return [{"tool": "maps_text_search", "args": {"keywords": user_input}}]


async def planner(state: TripState) -> dict:
    retry = state.get("retry_count", 0) + 1
    user_input = state.get("user_input", "")
    city = state.get("city", "")
    feedback = state.get("feedback")

    msg = f"用户需求:{user_input}"
    if city:
        msg += f"\n目的地:{city}"
    prior = prior_history(state.get("history") or [])
    if prior:
        msg = f"最近对话:\n{prior}\n\n{msg}"
    if feedback:
        msg += f"\n上次行程评价（请据此修正）:{feedback}"

    try:
        raw = await chat(PLANNER_PROMPT, msg, response_format="json_object")
        data = json.loads(raw)
        tasks = data.get("tasks") or _fallback(user_input, city)
    except Exception:  # noqa: BLE001
        tasks = _fallback(user_input, city)

    return {"tasks": tasks, "retry_count": retry}
