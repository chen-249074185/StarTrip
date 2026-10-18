"""查询改写：口语 query → 检索友好的多路查询。

输出 {dense_queries: [...], keywords: [...]}；LLM 失败/非法 JSON 时降级为原始 query。
"""

from __future__ import annotations

import json

from app.llm import chat

REWRITE_PROMPT = """你是检索查询改写器。根据用户需求与候选景点，输出 JSON：
{"dense_queries": ["...", "..."],   # 2~3 条，面向向量检索，补玩法/同义词/避坑
 "keywords": ["...", "..."]}         # 3~6 个，面向关键词精确匹配的地名/设施名
只输出 JSON，不要解释。"""


async def rewrite(user_input: str, spots: list[str] | None = None, city: str = "") -> dict:
    spots = spots or []
    msg = f"用户需求:{user_input}\n城市:{city}\n候选景点:{spots}"
    fallback = {"dense_queries": [f"{city} {user_input}".strip()], "keywords": spots[:5]}
    try:
        raw = await chat(REWRITE_PROMPT, msg, response_format="json_object")
        data = json.loads(raw)
        dense = data.get("dense_queries") or fallback["dense_queries"]
        kws = data.get("keywords") or fallback["keywords"]
        return {"dense_queries": dense[:3], "keywords": kws[:6]}
    except Exception:  # noqa: BLE001
        # LLM 失败/非法 JSON：降级为原始 query，保证链路不中断
        return fallback
