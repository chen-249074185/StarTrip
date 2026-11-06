"""RAG 节点：失败隔离 + 同轮缓存。"""

from __future__ import annotations

from app.nodes import retriever as retriever_mod


async def test_retriever_degrades_instead_of_raising(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("pg down")

    monkeypatch.setattr(retriever_mod, "rewrite", boom)
    out = await retriever_mod.retriever(
        {"user_input": "上海两日游", "city": "上海", "tool_results": {}}
    )
    assert out["rag_hints"] == []
    assert out["rag_degraded"] is True
    assert out["rag_key"]


async def test_retriever_reuses_result_within_same_turn(monkeypatch):
    calls = 0

    async def fake_rewrite(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {"dense_queries": ["上海"], "keywords": ["外滩"]}

    async def fake_dense(*args, **kwargs):
        return [1]

    async def fake_sparse(*args, **kwargs):
        return [1]

    async def fake_fetch(ids):
        return [{"id": 1, "content": "外滩攻略"}]

    monkeypatch.setattr(retriever_mod, "rewrite", fake_rewrite)
    monkeypatch.setattr(retriever_mod, "dense_search", fake_dense)
    monkeypatch.setattr(retriever_mod, "sparse_search", fake_sparse)
    monkeypatch.setattr(retriever_mod, "fetch_contents", fake_fetch)

    state = {"user_input": "上海两日游", "city": "上海", "tool_results": {}}
    first = await retriever_mod.retriever(state)
    assert first["rag_hints"] == ["外滩攻略"]

    state.update(first)
    second = await retriever_mod.retriever(state)
    assert second == {}
    assert calls == 1
