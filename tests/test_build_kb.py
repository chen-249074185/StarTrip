"""知识库构建：切块 + 按来源幂等重建。"""

from __future__ import annotations

from scripts import build_kb


def test_chunk_text_overlap_and_tail():
    text = "0123456789" * 10
    chunks = build_kb.chunk_text(text, size=20, overlap=5)

    assert all(len(c) <= 20 for c in chunks)
    assert chunks[0] == text[:20]
    assert chunks[0][-5:] == chunks[1][:5]
    assert "".join(chunks).count("0") >= 10
    assert build_kb.chunk_text("   ") == []


def test_chunk_markdown_keeps_sections():
    text = "# 上海旅游攻略\n\n## 景点\n外滩和豫园。\n\n## 交通\n地铁很方便。"
    chunks = build_kb.chunk_markdown(text, size=10, overlap=2)
    assert any("外滩" in chunk for chunk in chunks)
    assert any("地铁" in chunk for chunk in chunks)
    assert all(len(chunk) <= 10 for chunk in chunks)


async def test_replace_source_deletes_before_insert(monkeypatch):
    calls: list[tuple[str, tuple]] = []
    batches: list[tuple[str, list[tuple]]] = []

    async def fake_execute(query, params):
        calls.append((query, params))

    async def fake_execute_many(query, params_list):
        batches.append((query, params_list))

    monkeypatch.setattr(build_kb, "execute", fake_execute)
    monkeypatch.setattr(build_kb, "execute_many", fake_execute_many)
    monkeypatch.setattr(build_kb, "Vector", lambda emb: ("vec", len(emb)))

    total = await build_kb.replace_source(
        source="kb/shanghai.md",
        title="上海",
        chunks=["第一段", "第二段"],
        embs=[[0.1, 0.2], [0.3, 0.4]],
    )

    assert total == 2
    assert calls[0][0].startswith("DELETE FROM docs")
    assert calls[0][1] == ("kb/shanghai.md",)
    assert len(batches) == 1
    assert batches[0][0].startswith("INSERT INTO docs")
    assert len(batches[0][1]) == 2
    assert batches[0][1][0][0:3] == ("上海", "第一段", "kb/shanghai.md")
