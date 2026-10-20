"""推荐节点：按当前季节 + 知识库城市池推荐目的地（多样化），产出回复与可点选选项。"""

from __future__ import annotations

import json
import random

from app.db.pg import fetch
from app.llm import chat
from app.memory import prior_history
from app.state import TripState

RECOMMEND_PROMPT = """你是旅行推荐官。根据用户的话和当前季节，从给定的「城市池」里挑 5-6 个当季适合的目的地。
要求：多样化，不要每次都给同一批；理由要具体（结合该城当季特色）。
输出 JSON：
{"reply": "一句自然的话，说明现在是什么季节、适合去哪、为什么",
 "options": [{"label": "城市名", "value": "想去<城市>", "desc": "一句话理由"}]}
只输出 JSON，不要解释。"""


async def _city_pool() -> list[str]:
    try:
        rows = await fetch("SELECT DISTINCT title FROM docs")
        return [r["title"] for r in rows if r["title"]]
    except Exception:  # noqa: BLE001
        return []


async def recommend(state: TripState) -> dict:
    user_input = state.get("user_input", "")
    season = state.get("season", "")
    cities = await _city_pool()
    random.shuffle(cities)          # 每次顺序不同 → 推荐更多样
    pool = cities[:20]
    msg = f"用户说:{user_input}\n当前季节:{season}\n城市池:{pool}"
    prior = prior_history(state.get("history") or [])
    if prior:
        msg = f"最近对话:\n{prior}\n\n{msg}"
    try:
        raw = await chat(RECOMMEND_PROMPT, msg, response_format="json_object", temperature=0.9)
        data = json.loads(raw)
        return {
            "reply": data.get("reply") or f"现在是{season}季，想好去哪了吗？",
            "options": data.get("options") or [],
        }
    except Exception:  # noqa: BLE001
        return {"reply": "说说你想去哪个城市、几天、预算？", "options": []}
