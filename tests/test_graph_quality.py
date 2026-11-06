"""图级质量闭环：未接地景点被压分并触发重规划。"""

from __future__ import annotations

import json

from langgraph.checkpoint.memory import InMemorySaver

import app.graph as graph_module
from app.config import settings
from app.nodes import executor as executor_mod
from app.nodes import planner as planner_mod
from app.nodes import retriever as retriever_mod
from app.nodes import reviewer as reviewer_mod
from app.nodes import router as router_mod


async def fake_router_chat(system, user, **kwargs):
    return '{"intent": "plan", "city": "上海"}'


async def fake_planner_chat(system, user, **kwargs):
    return '{"tasks": [{"tool": "maps_text_search", "args": {"city": "上海", "keywords": "景点"}}]}'


async def fake_tool(args):
    return [
        json.dumps(
            {"pois": [{"name": "外滩", "location": "121.490,31.240"}]},
            ensure_ascii=False,
        )
    ]


async def fake_rewrite(user_input, spots=None, city=""):
    return {"dense_queries": [], "keywords": []}


async def fake_search(*args, **kwargs):
    return []


async def fake_fetch(ids):
    return []


async def fake_reviewer_chat(system, user, **kwargs):
    return json.dumps(
        {
            "trip_plan": {
                "days": [
                    {
                        "date": "D1",
                        "spots": [
                            {"name": "外滩", "time": "09:00-10:00"},
                            {"name": "迪士尼", "time": "11:00-12:00"},
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


async def test_graph_caps_hallucinated_plan(monkeypatch):
    monkeypatch.setattr(settings, "hitl_enabled", False)
    monkeypatch.setattr(settings, "trip_persist_enabled", False)
    monkeypatch.setattr(router_mod, "chat", fake_router_chat)
    monkeypatch.setattr(planner_mod, "chat", fake_planner_chat)
    monkeypatch.setattr(executor_mod, "get_tool", lambda name: fake_tool)
    monkeypatch.setattr(retriever_mod, "rewrite", fake_rewrite)
    monkeypatch.setattr(retriever_mod, "dense_search", fake_search)
    monkeypatch.setattr(retriever_mod, "sparse_search", fake_search)
    monkeypatch.setattr(retriever_mod, "fetch_contents", fake_fetch)
    monkeypatch.setattr(reviewer_mod, "chat", fake_reviewer_chat)

    graph = graph_module.compile_graph(InMemorySaver())
    cfg = {"configurable": {"thread_id": "test-graph-quality"}}
    final = await graph.ainvoke(
        {"user_input": "上海一日游", "session_id": "test-graph-quality"}, cfg
    )

    assert final["score"] == 55.0
    assert final["grounding"]["ungrounded"] == ["迪士尼"]
    # 3 次规划（首次 + 2 次重规划）后仍未达标，收尾返回最佳草稿
    assert final["retry_count"] == 3
    assert "找不到依据" in final["feedback"]
