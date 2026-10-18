"""路由节点：判定意图（recommend / plan）+ 抽取目的地 + 计算当前季节。"""

from __future__ import annotations

import json
from datetime import date

from app.llm import chat
from app.state import TripState

ROUTER_PROMPT = """你是旅行助手的意图路由器。判断用户这句话：
- "plan"：用户明确说了想去的目的地（城市 / 地区）
- "recommend"：表达了想出行 / 旅游 / 玩的意愿，但没给目的地（如"我想出去玩""有什么推荐""想散散心"）
- "chat"：与出行旅游完全无关的话题（如"你是谁""今天几号""讲个笑话"）
输出 JSON：{"intent": "plan"|"recommend"|"chat", "city": "目的地，没有则空字符串"}
只输出 JSON，不要解释。"""

_TRAVEL_HINTS = ("玩", "旅游", "旅行", "出游", "去哪", "推荐", "度假", "散心", "假期", "周末去哪")

_SEASON_BY_MONTH = {
    12: "冬", 1: "冬", 2: "冬",
    3: "春", 4: "春", 5: "春",
    6: "夏", 7: "夏", 8: "夏",
    9: "秋", 10: "秋", 11: "秋",
}


def current_season() -> str:
    return _SEASON_BY_MONTH[date.today().month]


async def router(state: TripState) -> dict:
    user_input = state.get("user_input", "")
    season = state.get("season") or current_season()
    try:
        raw = await chat(ROUTER_PROMPT, user_input, response_format="json_object")
        data = json.loads(raw)
        intent = data.get("intent") or "recommend"
        city = (data.get("city") or "").strip()
    except Exception:  # noqa: BLE001
        intent, city = "recommend", ""
    if intent == "plan" and not city:
        intent = "recommend"
    # 关键词兜底：LLM 误判成 chat，但明显在聊出行 → recommend
    if intent == "chat" and any(k in user_input for k in _TRAVEL_HINTS):
        intent = "recommend"
    return {"intent": intent, "city": city, "season": season}
