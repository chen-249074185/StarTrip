"""行程确定性校验：时间、预算、重复、必去/避开、天数。

LLM 负责“好不好玩”，这里负责“可不可行”。校验失败时把结构化错误回给
Planner/Reviewer，而不是只给一个模糊分数。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.plan import normalize_plan

_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")
_BUDGET_RE = re.compile(r"(?:预算|人均|总共)\s*(\d{1,6})")
_AMOUNT_RE = re.compile(r"(\d{3,6})\s*元")
_DAYS_RE = re.compile(r"([一二两三四五六七八九十\d]{1,2})\s*(?:天|日游)")

_CN_NUM = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "checks": self.checks,
            "metrics": self.metrics,
        }

    def feedback(self) -> str:
        if self.ok:
            return "行程校验通过"
        return "行程校验未通过：" + "；".join(self.errors)


def _to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def _parse_minutes(text: str) -> tuple[int, int] | None:
    match = _TIME_RE.match(str(text or ""))
    if not match:
        return None
    start_h, start_m, end_h, end_m = (int(x) for x in match.groups())
    if start_h > 23 or end_h > 23 or start_m > 59 or end_m > 59:
        return None
    return start_h * 60 + start_m, end_h * 60 + end_m


def _parse_days(text: str) -> int | None:
    match = _DAYS_RE.search(str(text or ""))
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    return _CN_NUM.get(raw)


def extract_constraints(user_input: str) -> dict:
    """从自然语言里抽取预算/天数；抽不到返回 None，校验时跳过。"""
    text = str(user_input or "")
    budget_match = _BUDGET_RE.search(text) or _AMOUNT_RE.search(text)
    return {
        "budget": int(budget_match.group(1)) if budget_match else None,
        "days": _parse_days(text),
    }


def validate_plan(
    plan: Any,
    *,
    user_input: str = "",
    budget: int | None = None,
    days: int | None = None,
    must_include: list[str] | None = None,
    must_avoid: list[str] | None = None,
    travel_times: dict[tuple[str, str], int] | None = None,
) -> ValidationResult:
    """返回结构化校验结果；errors 非空即不可行。"""
    normalized = normalize_plan(plan)
    constraints = extract_constraints(user_input)
    budget = budget if budget is not None else constraints["budget"]
    expected_days = days if days is not None else constraints["days"]
    required = [str(x) for x in (must_include or []) if str(x).strip()]
    forbidden = [str(x) for x in (must_avoid or []) if str(x).strip()]
    travel_times = travel_times or {}

    errors: list[str] = []
    warnings: list[str] = []
    checks = {
        "structure": True,
        "days": True,
        "time": True,
        "budget": True,
        "duplicates": True,
        "must_include": True,
        "must_avoid": True,
    }

    plan_days = normalized.get("days") or []
    if not plan_days:
        checks["structure"] = False
        errors.append("行程为空或结构不完整")

    if expected_days and len(plan_days) < expected_days:
        checks["days"] = False
        errors.append(f"天数不足：需要 {expected_days} 天，实际 {len(plan_days)} 天")
    elif expected_days and len(plan_days) > expected_days:
        warnings.append(f"天数超出：需要 {expected_days} 天，实际 {len(plan_days)} 天")

    names: list[str] = []
    total_budget = 0
    missing_time = 0
    time_conflicts = 0
    duplicate_count = 0

    for day in plan_days:
        intervals: list[tuple[int, int, str]] = []
        for spot in day.get("spots") or []:
            name = str(spot.get("name") or "").strip()
            if name:
                names.append(name)
            total_budget += _to_int(spot.get("budget")) or 0

            parsed = _parse_minutes(spot.get("time"))
            if parsed is None:
                missing_time += 1
                continue
            start, end = parsed
            if end <= start:
                checks["time"] = False
                time_conflicts += 1
                errors.append(f"{name or '景点'} 时间不合法：{spot.get('time')}")
                continue
            if start < 8 * 60 or end > 22 * 60:
                warnings.append(f"{name or '景点'} 不在 08:00–22:00 内：{spot.get('time')}")
            intervals.append((start, end, name))

        intervals.sort(key=lambda x: x[0])
        for i in range(1, len(intervals)):
            _, prev_end, prev_name = intervals[i - 1]
            start, end, name = intervals[i]
            if start < prev_end:
                checks["time"] = False
                time_conflicts += 1
                errors.append(f"{prev_name} 与 {name} 时间重叠")
                continue
            travel = travel_times.get((prev_name, name))
            if travel is not None and start - prev_end < travel:
                checks["time"] = False
                time_conflicts += 1
                errors.append(f"{prev_name} → {name} 路程 {travel} 分钟，间隔不足")

    # 逐项预算与按天预算取较大值：LLM 可能只填其中一个
    day_budget = sum(_to_int(day.get("budget_total")) or 0 for day in plan_days)
    total_budget = max(total_budget, day_budget)
    if budget is not None and total_budget > budget:
        checks["budget"] = False
        errors.append(f"预算超支：合计 {total_budget} 元，上限 {budget} 元")
    elif budget is not None and total_budget == 0:
        warnings.append("行程未给出预算明细")

    seen: set[str] = set()
    for name in names:
        if name in seen:
            duplicate_count += 1
        seen.add(name)
    if duplicate_count:
        checks["duplicates"] = False
        errors.append(f"存在重复景点：{duplicate_count} 个")

    all_text = " ".join(names)
    missing_required = [x for x in required if x not in all_text]
    if missing_required:
        checks["must_include"] = False
        errors.append(f"缺少必去景点：{'、'.join(missing_required)}")
    hit_forbidden = [x for x in forbidden if x in all_text]
    if hit_forbidden:
        checks["must_avoid"] = False
        errors.append(f"命中了避开项：{'、'.join(hit_forbidden)}")

    if missing_time:
        warnings.append(f"{missing_time} 个景点缺少时间，无法校验时间冲突")

    return ValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        checks=checks,
        metrics={
            "days": len(plan_days),
            "spots": len(names),
            "budget_total": total_budget,
            "budget_limit": budget,
            "missing_time": missing_time,
            "time_conflicts": time_conflicts,
            "duplicates": duplicate_count,
        },
    )
