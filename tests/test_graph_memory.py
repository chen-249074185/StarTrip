"""图级多轮记忆：假 LLM/工具 + InMemorySaver，验证同 thread 跨轮携带历史。"""

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

planner_prompts: list[str] = []


async def fake_router_chat(system, user, **kwargs):
    return '{"intent": "plan", "city": "上海"}'


async def fake_planner_chat(system, user, **kwargs):
    planner_prompts.append(user)
    return '{"tasks": [{"tool": "maps_text_search", "args": {"keywords": "景点", "city": "上海"}}]}'


async def fake_tool(args):
    return ["外滩"]


async def fake_rewrite(user_input, spots=None, city=""):
    return {"dense_queries": [], "keywords": []}


async def fake_dense_search(queries, topn=20):
    return []


async def fake_sparse_search(keywords, topn=20):
    return []


async def fake_fetch_contents(ids):
    return []


async def fake_reviewer_chat(system, user, **kwargs):
    return json.dumps(
        {
            "trip_plan": {
                "days": [{"date": "D1", "spots": [{"name": "外滩"}]}],
            },
            "score": 90,
            "reply": "已安排 D1 外滩",
            "feedback": "",
        },
        ensure_ascii=False,
    )


async def test_multi_turn_history_reaches_planner(monkeypatch):
    planner_prompts.clear()
    monkeypatch.setattr(settings, "hitl_enabled", False)
    monkeypatch.setattr(settings, "trip_persist_enabled", False)
    monkeypatch.setattr(router_mod, "chat", fake_router_chat)
    monkeypatch.setattr(planner_mod, "chat", fake_planner_chat)
    monkeypatch.setattr(executor_mod, "get_tool", lambda name: fake_tool)
    monkeypatch.setattr(retriever_mod, "rewrite", fake_rewrite)
    monkeypatch.setattr(retriever_mod, "dense_search", fake_dense_search)
    monkeypatch.setattr(retriever_mod, "sparse_search", fake_sparse_search)
    monkeypatch.setattr(retriever_mod, "fetch_contents", fake_fetch_contents)
    monkeypatch.setattr(reviewer_mod, "chat", fake_reviewer_chat)

    graph = graph_module.compile_graph(InMemorySaver())
    cfg = {"configurable": {"thread_id": "test-graph-memory"}}

    async for _ in graph.astream(
        {"user_input": "上海两日游", "session_id": "test-graph-memory"}, cfg
    ):
        pass
    first = await graph.aget_state(cfg)
    assert first.values["score"] == 90
    assert first.values["history"][-1]["role"] == "assistant"
    assert "D1: 外滩" in first.values["history"][-1]["content"]

    async for _ in graph.astream(
        {"user_input": "第二天不要博物馆", "session_id": "test-graph-memory"}, cfg
    ):
        pass
    second = await graph.aget_state(cfg)
    assert second.values["score"] == 90
    assert any("上海两日游" in m["content"] for m in second.values["history"])
    assert "D1: 外滩" in planner_prompts[-1]
    assert "第二天不要博物馆" in planner_prompts[-1]
