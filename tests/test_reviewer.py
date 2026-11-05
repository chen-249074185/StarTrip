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
