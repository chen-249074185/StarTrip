"""评测指标：约束命中 + 汇总。"""

from __future__ import annotations

from typing import Any


def plan_spot_names(plan: dict | None) -> list[str]:
    names: list[str] = []
    for day in (plan or {}).get("days") or []:
        for spot in day.get("spots") or []:
            name = spot.get("name")
            if name:
                names.append(str(name))
    return names


def match_constraints(plan: dict | None, case: dict) -> dict:
    """检查 must_include / must_avoid（子串匹配，够用且可解释）。"""
    text = " ".join(plan_spot_names(plan))
    required = [str(x) for x in case.get("must_include") or []]
    forbidden = [str(x) for x in case.get("must_avoid") or []]
    return {
        "include_required": required,
        "include_hits": [x for x in required if x in text],
        "avoid_hits": [x for x in forbidden if x in text],
    }


def aggregate(rows: list[dict[str, Any]]) -> dict:
    """把逐条评测结果汇总成可对比的指标。"""
    n = len(rows)
    if not n:
        return {"cases": 0}

    def avg(getter) -> float:
        return round(sum(getter(row) for row in rows) / n, 4)

    include_total = sum(len(row["constraints"]["include_required"]) for row in rows)
    include_hits = sum(len(row["constraints"]["include_hits"]) for row in rows)
    avoid_hits = sum(len(row["constraints"]["avoid_hits"]) for row in rows)

    return {
        "cases": n,
        "factual_consistency": avg(lambda r: r["judge"]["factual_consistency"]),
        "grounded_rate": avg(lambda r: r["judge"]["grounded_rate"]),
        "format_valid_rate": avg(lambda r: 1.0 if r["judge"]["format_valid"] else 0.0),
        "constraint_include_rate": round(include_hits / include_total, 4)
        if include_total
        else 1.0,
        "constraint_avoid_hits": avoid_hits,
        "avg_review_score": avg(lambda r: float(r.get("score") or 0)),
    }
