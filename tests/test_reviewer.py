"""审查节点：评分容错解析 + LLM 失败降级。"""

from __future__ import annotations

import json

from app.nodes import reviewer as reviewer_mod
from app.nodes.reviewer import _parse_score, reviewer


def test_parse_score_tolerates_text_and_clamps():
    assert _parse_score(88) == 88.0
    assert _parse_score("88") == 88.0
    assert _parse_score("综合 88.5 分") == 88.5
    assert _parse_score(None) == 0.0
    assert _parse_score("无") == 0.0
    assert _parse_score(120) == 100.0
    assert _parse_score(-3) == 0.0


async def test_reviewer_keeps_plan_when_score_is_text(monkeypatch):
    async def fake_chat(system, user, **kwargs):
        return json.dumps(
            {
                "trip_plan": {"days": [{"date": "D1", "spots": [{"name": "外滩"}]}]},
                "score": "88分",
                "reply": "已安排",
                "feedback": "",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(reviewer_mod, "chat", fake_chat)
    out = await reviewer({"user_input": "上海一日游", "city": "上海"})

    assert out["score"] == 88.0
    assert out["trip_plan"]["days"][0]["spots"][0]["name"] == "外滩"


async def test_reviewer_degrades_on_llm_error(monkeypatch):
    async def boom(system, user, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(reviewer_mod, "chat", boom)
    out = await reviewer({"user_input": "上海一日游"})

    assert out["score"] == 0.0
    assert out["trip_plan"] == {"days": []}
    assert out["feedback"]


async def test_reviewer_enforces_prefs_must_avoid(monkeypatch):
    async def fake_chat(system, user, **kwargs):
        return json.dumps(
            {
                "trip_plan": {
                    "days": [
                        {
                            "date": "D1",
                            "spots": [{"name": "外滩", "time": "09:00-10:30"}],
                        }
                    ]
                },
                "score": 95,
                "reply": "已安排",
                "feedback": "",
            },
            ensure_ascii=False,
        )

    async def fake_prefs(session_id):
        return {"must_avoid": ["外滩"]}

    monkeypatch.setattr(reviewer_mod, "chat", fake_chat)
    monkeypatch.setattr(reviewer_mod, "get_prefs", fake_prefs)
    out = await reviewer({"user_input": "上海一日游", "session_id": "s"})

    assert out["score"] == 60.0
    assert out["validation"]["checks"]["must_avoid"] is False
    assert "避开" in out["validation"]["errors"][0]


async def test_reviewer_caps_ungrounded_plan(monkeypatch):
    async def fake_chat(system, user, **kwargs):
        return json.dumps(
            {
                "trip_plan": {
                    "days": [
                        {
                            "date": "D1",
                            "spots": [
                                {"name": "外滩", "time": "09:00-10:30"},
                                {"name": "不存在的景点", "time": "11:00-12:00"},
                            ],
                        }
                    ]
                },
                "score": 95,
                "reply": "已安排",
                "feedback": "",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(reviewer_mod, "chat", fake_chat)
    tool_results = {
        "maps_text_search": [
            json.dumps(
                {"pois": [{"name": "外滩", "location": "121.490,31.240"}]},
                ensure_ascii=False,
            )
        ]
    }
    out = await reviewer(
        {"user_input": "上海一日游", "tool_results": tool_results, "rag_hints": []}
    )

    assert out["grounding"]["ungrounded"] == ["不存在的景点"]
    assert out["score"] == 55.0
    assert "找不到依据" in out["feedback"]
