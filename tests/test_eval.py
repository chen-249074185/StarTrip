"""评测单测：judge 解析/降级、结构校验、约束与汇总。"""

from __future__ import annotations

import json
from pathlib import Path

from app.eval import judge as judge_mod
from app.eval.judge import check_format, judge_trip
from app.eval.metrics import aggregate, match_constraints


def _plan() -> dict:
    return {
        "days": [
            {"date": "D1", "spots": [{"name": "外滩"}, {"name": "豫园"}]},
        ]
    }


def test_check_format():
    assert check_format(_plan())
    assert not check_format({"days": []})
    assert not check_format({"days": [{"date": "D1", "spots": [{}]}]})
    assert not check_format(None)


async def test_judge_clamps_scores(monkeypatch):
    async def fake_chat(system, user, **kwargs):
        return '{"factual_consistency": 1.4, "grounded_rate": -0.2, "issues": ["票价缺失"]}'

    monkeypatch.setattr(judge_mod, "chat", fake_chat)
    result = await judge_trip("上海两日游", _plan(), {"tool_results": {}})
    assert result["factual_consistency"] == 1.0
    assert result["grounded_rate"] == 0.0
    assert result["format_valid"] is True
    assert result["issues"] == ["票价缺失"]


async def test_judge_fallback(monkeypatch):
    async def boom(system, user, **kwargs):
        raise RuntimeError("judge down")

    monkeypatch.setattr(judge_mod, "chat", boom)
    result = await judge_trip("q", _plan())
    assert result["factual_consistency"] == 0.0
    assert result["format_valid"] is True
    assert "judge down" in result["issues"][0]


def test_constraints_and_aggregate():
    constraints = match_constraints(
        _plan(),
        {"must_include": ["外滩", "迪士尼"], "must_avoid": ["豫园"]},
    )
    assert constraints["include_hits"] == ["外滩"]
    assert constraints["avoid_hits"] == ["豫园"]

    rows = [
        {
            "score": 90,
            "judge": {
                "factual_consistency": 0.8,
                "grounded_rate": 0.6,
                "format_valid": True,
            },
            "constraints": constraints,
        },
        {
            "score": 70,
            "judge": {
                "factual_consistency": 0.4,
                "grounded_rate": 0.2,
                "format_valid": False,
            },
            "constraints": {
                "include_required": ["西湖"],
                "include_hits": [],
                "avoid_hits": [],
            },
        },
    ]
    summary = aggregate(rows)
    assert summary["cases"] == 2
    assert summary["factual_consistency"] == 0.6
    assert summary["grounded_rate"] == 0.4
    assert summary["format_valid_rate"] == 0.5
    assert summary["constraint_include_rate"] == 0.3333
    assert summary["constraint_avoid_hits"] == 1
    assert summary["avg_review_score"] == 80.0


def test_golden_set_schema():
    data = json.loads(Path("tests/eval/golden.json").read_text(encoding="utf-8"))
    assert len(data) >= 10
    ids = [case["id"] for case in data]
    assert len(ids) == len(set(ids))
    for case in data:
        assert case["input"]
        assert case["must_include"]
