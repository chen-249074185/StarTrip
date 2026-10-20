"""Checkpoint 集成测试：PG 未启动时自动 skip。"""

from __future__ import annotations

import socket
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph

from app.db.checkpoint import init_checkpointer
from app.db.pg import close_pool, open_pool


def _pg_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _pg_up(), reason="PostgreSQL 未启动")


class CounterState(TypedDict, total=False):
    n: int


async def _inc(state: CounterState) -> dict:
    return {"n": state.get("n", 0) + 1}


async def test_checkpoint_persists_across_compiles():
    close_pool()
    open_pool()
    thread_id = f"test-{uuid4().hex[:8]}"
    try:
        saver = await init_checkpointer()
        builder = StateGraph(CounterState)
        builder.add_node("inc", _inc)
        builder.add_edge(START, "inc")
        builder.add_edge("inc", END)
        cfg = {"configurable": {"thread_id": thread_id}}

        graph1 = builder.compile(checkpointer=saver)
        async for _ in graph1.astream({"n": 0}, cfg):
            pass
        assert (await graph1.aget_state(cfg)).values["n"] == 1

        graph2 = builder.compile(checkpointer=saver)
        assert (await graph2.aget_state(cfg)).values["n"] == 1

        async for _ in graph2.astream({"n": 10}, cfg):
            pass
        assert (await graph2.aget_state(cfg)).values["n"] == 11

        await saver.adelete_thread(thread_id)
    finally:
        close_pool()
