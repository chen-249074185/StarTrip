"""审查节点：LLM 生成行程 + 5 维评分 + 不达标 feedback。"""

from __future__ import annotations

import json

from app.llm import chat
from app.state import TripState

REVIEWER_PROMPT = """你是行程审查官。根据用户需求、工具结果与攻略知识，生成完整行程并评分。

输出 JSON：
{
  "trip_plan": {"days": [{"date": "D1", "spots": [{"name": "...", "time": "09:00-11:00",
     "transport": "...", "budget": 0, "note": "..."}], "budget_total": 0}]},
  "score": 0-100,
  "dimensions": {"时间衔接": 0, "距离合理性": 0, "偏好匹配": 0, "预算控制": 0, "天气适配": 0},
  "feedback": "若不达标，指出哪条失分（达标则空字符串）"
}
注意：攻略知识（RAG）是**可选补充**，若与目的地无关或缺失，请直接忽略，**不要因此扣分**；
评分只依据【时间衔接 / 距离合理性 / 偏好匹配 / 预算控制 / 天气适配】五个维度。
只输出 JSON，不要解释。"""


async def reviewer(state: TripState) -> dict:
    user_input = state.get("user_input", "")
    tool_results = state.get("tool_results", {})
    rag_hints = state.get("rag_hints", [])

    msg = (
        f"用户需求:{user_input}\n"
        f"工具结果:{json.dumps(tool_results, ensure_ascii=False)[:4000]}\n"
        f"攻略知识:{rag_hints}"
    )
    try:
        raw = await chat(REVIEWER_PROMPT, msg, response_format="json_object")
        data = json.loads(raw)
        return {
            "trip_plan": data.get("trip_plan") or {"days": []},
            "score": float(data.get("score") or 0),
            "feedback": data.get("feedback") or None,
        }
    except Exception:  # noqa: BLE001
        return {"trip_plan": {"days": []}, "score": 0.0, "feedback": "生成失败，请重试"}
