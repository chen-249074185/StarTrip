"""HITL 单测：interrupt 暂停/恢复、开关直通、payload 提取。"""

from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.config import settings
from app.main import interrupt_payload
from app.nodes.confirm import confirm


class HitlState(TypedDict, total=False):
    tasks: list[dict]
    executed: bool


async def _after(state: HitlState) -> dict:
    return {"executed": True}


def _build_graph():
    builder = StateGraph(HitlState)
    builder.add_node("confirm", confirm)
    builder.add_node("after", _after)
    builder.add_edge(START, "confirm")
    builder.add_edge("confirm", "after")
    builder.add_edge("after", END)
    return builder.compile(checkpointer=InMemorySaver())


async def test_interrupt_then_resume(monkeypatch):
    monkeypatch.setattr(settings, "hitl_enabled", True)
    graph = _build_graph()
    cfg = {"configurable": {"thread_id": "test-hitl"}}
    original = [
        {"tool": "maps_text_search", "args": {"keywords": "景点", "city": "上海"}}
    ]

    async for _ in graph.astream({"tasks": original}, cfg):
        pass
    snapshot = await graph.aget_state(cfg)
    assert snapshot.next == ("confirm",)
    assert interrupt_payload(snapshot)["tasks"] == original

    edited = [{"tool": "maps_weather", "args": {"city": "上海"}}]
    async for _ in graph.astream(Command(resume={"tasks": edited}), cfg):
        pass
    resumed = await graph.aget_state(cfg)
    assert resumed.next == ()
    assert resumed.values["tasks"] == edited
    assert resumed.values["executed"] is True
    assert interrupt_payload(resumed) is None


async def test_confirm_pass_through_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "hitl_enabled", False)
    assert await confirm({"tasks": [{"tool": "x"}]}) == {}


async def test_confirm_skips_retry(monkeypatch):
    monkeypatch.setattr(settings, "hitl_enabled", True)
    state = {"tasks": [{"tool": "x"}], "retry_count": 2}
    assert await confirm(state) == {}
