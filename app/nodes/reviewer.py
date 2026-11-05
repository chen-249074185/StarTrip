"""审查节点：LLM 生成行程 + 5 维评分 + 不达标 feedback。"""

from __future__ import annotations

import json
import re
from typing import Any

from app.llm import chat
from app.memory import prior_history
from app.plan import normalize_plan, plan_is_usable
from app.prefs import format_prefs, get_prefs
from app.state import TripState
from app.validate import validate_plan

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


_SCORE_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_score(value: Any) -> float:
    """容错解析评分：兼容 "88" / "88分" / 88.5，并夹到 0~100。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        match = _SCORE_RE.search(str(value or ""))
        num = float(match.group()) if match else 0.0
    return max(0.0, min(100.0, num))


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
        plan = normalize_plan(data.get("trip_plan"))
        score = _parse_score(data.get("score"))
        feedback = data.get("feedback") or None
        validation = validate_plan(plan, user_input=user_input)
        if not plan_is_usable(plan):
            # 结构不完整时不能给高分，否则会把空行程当成功结果落库
            score = 0.0
            feedback = feedback or "行程结构不完整（缺少日期或景点）"
        elif not validation.ok:
            # 确定性校验失败：压分并回传结构化错误，触发 Planner 重规划
            score = min(score, 60.0)
            text = validation.feedback()
            feedback = f"{feedback}；{text}" if feedback else text
        return {
            "trip_plan": plan,
            "score": score,
            "reply": data.get("reply") or "",
            "feedback": feedback,
            "validation": validation.to_dict(),
        }
    except Exception:  # noqa: BLE001
        return {"trip_plan": {"days": []}, "score": 0.0, "reply": "", "feedback": "生成失败，请重试"}
