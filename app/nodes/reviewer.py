"""审查节点：LLM 生成行程 + 5 维评分 + 不达标 feedback。"""

from __future__ import annotations

import json

from app.llm import chat
from app.memory import prior_history
from app.prefs import format_prefs, get_prefs
from app.state import TripState

REVIEWER_PROMPT = """你是行程审查官。根据用户需求、工具结果与攻略知识，生成完整行程并评分。
若用户是在上一轮行程上提修改（如"第二天不要博物馆"），请结合「最近对话」中的行程摘要，保留未要求改动的部分。

输出 JSON：
{
  "trip_plan": {"days": [{"date": "D1", "spots": [{"name": "...", "time": "09:00-11:00",
     "transport": "...", "budget": 0, "note": "..."}], "budget_total": 0}]},
  "score": 0-100,
  "dimensions": {"时间衔接": 0, "距离合理性": 0, "偏好匹配": 0, "预算控制": 0, "天气适配": 0},
  "reply": "给用户的一句自然语言总结（如：给你安排了上海两日游，D1 外滩…，综合评分 88 分）",
  "feedback": "若不达标，指出哪条失分（达标则空字符串）"
}
注意：攻略知识（RAG）是**可选补充**，若与目的地无关或缺失，请直接忽略，**不要因此扣分**；
评分只依据【时间衔接 / 距离合理性 / 偏好匹配 / 预算控制 / 天气适配】五个维度。
只输出 JSON，不要解释。"""


async def reviewer(state: TripState) -> dict:
    user_input = state.get("user_input", "")
    tool_results = state.get("tool_results", {})
    rag_hints = state.get("rag_hints", [])

    prior = prior_history(state.get("history") or [])
    pref_text = format_prefs(await get_prefs(state.get("session_id", "")))
    msg = (
        (f"最近对话:\n{prior}\n\n" if prior else "")
        + f"用户需求:{user_input}\n"
        + (f"已知偏好:{pref_text}\n" if pref_text else "")
        + f"工具结果:{json.dumps(tool_results, ensure_ascii=False)[:4000]}\n"
        + f"攻略知识:{rag_hints}"
    )
    try:
        raw = await chat(REVIEWER_PROMPT, msg, response_format="json_object")
        data = json.loads(raw)
        return {
            "trip_plan": data.get("trip_plan") or {"days": []},
            "score": float(data.get("score") or 0),
            "reply": data.get("reply") or "",
            "feedback": data.get("feedback") or None,
        }
    except Exception:  # noqa: BLE001
        return {"trip_plan": {"days": []}, "score": 0.0, "reply": "", "feedback": "生成失败，请重试"}
