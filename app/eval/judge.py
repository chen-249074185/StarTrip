"""独立 LLM-as-judge：与 reviewer 解耦，只做事实/有据评估。

- 生成与评判是两次独立 LLM 调用，避免"自己评自己"
- `format_valid` 用确定性代码检查，不交给 LLM（更稳定）
- 无法核实的景点不算事实错误，但也不计入"有据"
"""

from __future__ import annotations

import json
from typing import Any

from app.llm import chat

JUDGE_PROMPT = """你是独立的事实审查员，不参与行程生成。根据【用户需求】【证据】【行程】评估：
1. factual_consistency（0~1）：行程中的景点/门票/开放时间/交通是否与证据一致；无法核实的项不算错误，但也不算有据。
2. grounded_rate（0~1）：行程中的景点有多大比例能在证据（工具结果 / 攻略知识）中找到依据。
3. issues：列出具体问题（最多 5 条），没有则空数组。

评分锚点：1.0=全部一致且有据；0.5=部分可核实/部分缺失；0=明显编造或与证据矛盾。
输出 JSON：{"factual_consistency": 0~1, "grounded_rate": 0~1, "issues": ["..."]}
只输出 JSON，不要解释。"""


def check_format(plan: Any) -> bool:
    """确定性结构校验：days[].date + spots[].name 必须存在。"""
    if not isinstance(plan, dict):
        return False
    days = plan.get("days")
    if not isinstance(days, list) or not days:
        return False
    for day in days:
        if not isinstance(day, dict) or not day.get("date"):
            return False
        spots = day.get("spots")
        if not isinstance(spots, list) or not spots:
            return False
        for spot in spots:
            if not isinstance(spot, dict) or not spot.get("name"):
                return False
    return True


def _clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


async def judge_trip(
    user_input: str,
    trip_plan: dict | None,
    evidence: dict | None = None,
) -> dict:
    """调用独立裁判，返回 {factual_consistency, grounded_rate, format_valid, issues}。"""
    plan_text = json.dumps(trip_plan or {}, ensure_ascii=False)[:4000]
    evidence_text = json.dumps(evidence or {}, ensure_ascii=False)[:4000]
    msg = (
        f"用户需求:{user_input}\n"
        f"证据:{evidence_text}\n"
        f"行程:{plan_text}"
    )
    try:
        raw = await chat(
            JUDGE_PROMPT, msg, response_format="json_object", temperature=0.0
        )
        data = json.loads(raw)
        issues = data.get("issues") or []
        return {
            "factual_consistency": _clamp01(data.get("factual_consistency")),
            "grounded_rate": _clamp01(data.get("grounded_rate")),
            "format_valid": check_format(trip_plan),
            "issues": [str(x) for x in issues][:5],
        }
    except Exception as e:  # noqa: BLE001
        return {
            "factual_consistency": 0.0,
            "grounded_rate": 0.0,
            "format_valid": check_format(trip_plan),
            "issues": [f"judge 调用失败: {e}"],
        }
