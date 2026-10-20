"""多轮记忆单测：历史裁剪 / 去重 / 摘要 / router 重置。"""

from __future__ import annotations

from app.memory import append_message, format_history, prior_history
from app.nodes import router as router_mod
from app.nodes.remember import remember
from app.nodes.router import router


def test_append_message_dedupes_and_trims():
    history: list[dict] = []
    history = append_message(history, "user", "上海两日游")
    history = append_message(history, "assistant", "好的")
    history = append_message(history, "assistant", "好的")
    assert len(history) == 2

    for i in range(12):
        history = append_message(history, "user", f"第{i}轮")
    assert len(history) == 10
    assert history[-1]["content"] == "第11轮"


def test_format_and_prior_history():
    history = [
        {"role": "user", "content": "上海两日游"},
        {"role": "assistant", "content": "D1 外滩"},
        {"role": "user", "content": "第二天不要博物馆"},
    ]
    prior = prior_history(history)
    assert "上海两日游" in prior
    assert "D1 外滩" in prior
    assert "第二天不要博物馆" not in prior
    assert "第二天不要博物馆" in format_history(history)


async def test_remember_includes_plan_digest():
    state = {
        "reply": "已安排",
        "trip_plan": {
            "days": [
                {"date": "D1", "spots": [{"name": "外滩"}, {"name": "豫园"}]},
            ]
        },
    }
    out = await remember(state)
    content = out["history"][-1]["content"]
    assert content.startswith("已安排")
    assert "行程安排：D1: 外滩、豫园" in content


async def test_router_appends_user_and_resets_turn(monkeypatch):
    captured: dict = {}

    async def fake_chat(system, user, **kwargs):
        captured["user"] = user
        return '{"intent": "plan", "city": "上海"}'

    monkeypatch.setattr(router_mod, "chat", fake_chat)

    state = {
        "user_input": "第二天不要博物馆",
        "history": [
            {"role": "user", "content": "上海两日游"},
            {"role": "assistant", "content": "D1 外滩、豫园"},
        ],
        "score": 90.0,
        "retry_count": 3,
        "trip_plan": {"days": []},
        "tasks": [{"tool": "old"}],
    }
    out = await router(state)

    assert out["intent"] == "plan"
    assert out["city"] == "上海"
    assert out["score"] is None
    assert out["retry_count"] == 0
    assert out["trip_plan"] is None
    assert out["tasks"] == []
    assert out["history"][-1] == {"role": "user", "content": "第二天不要博物馆"}
    assert "D1 外滩、豫园" in captured["user"]
    assert "第二天不要博物馆" in captured["user"]
