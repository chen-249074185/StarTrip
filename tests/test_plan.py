"""行程归一化：脏 JSON → 可落库/可渲染结构。"""

from __future__ import annotations

import json

from app.nodes import reviewer as reviewer_mod
from app.nodes.reviewer import reviewer
from app.plan import normalize_plan, plan_is_usable


def test_normalize_valid_plan_keeps_fields():
    plan = {
        "days": [
            {
                "date": "D1",
                "budget_total": 300,
                "spots": [
                    {"name": "外滩", "time": "09:00", "budget": 0},
                    {"name": " 豫园 "},
                ],
            }
        ]
    }
    out = normalize_plan(plan)

    assert out["days"][0]["budget_total"] == 300
    assert out["days"][0]["spots"][0]["time"] == "09:00"
    assert out["days"][0]["spots"][1]["name"] == "豫园"
    assert plan_is_usable(out)


def test_normalize_rejects_wrong_root_and_days():
    assert normalize_plan(None) == {"days": []}
    assert normalize_plan("oops") == {"days": []}
    assert normalize_plan({"days": "D1"}) == {"days": []}
    assert not plan_is_usable({"days": []})


def test_normalize_drops_invalid_days_and_spots():
    plan = {
        "days": [
            "not-a-day",
            {"date": "D2", "spots": "not-a-list"},
            {"date": "D3", "spots": [None, 3, {"time": "10:00"}, {"name": "  "}]},
            {"date": "", "spots": ["外滩", {"name": "南京路"}]},
        ]
    }
    out = normalize_plan(plan)

    assert len(out["days"]) == 1
    assert out["days"][0]["date"] == "D4"
    assert [s["name"] for s in out["days"][0]["spots"]] == ["外滩", "南京路"]


async def test_reviewer_downgrades_malformed_plan(monkeypatch):
    async def fake_chat(system, user, **kwargs):
        return json.dumps(
            {
                "trip_plan": {"days": "D1 外滩"},
                "score": 95,
                "reply": "看起来不错",
                "feedback": "",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(reviewer_mod, "chat", fake_chat)
    out = await reviewer({"user_input": "上海一日游", "city": "上海"})

    assert out["trip_plan"] == {"days": []}
    assert out["score"] == 0.0
    assert "结构不完整" in out["feedback"]
