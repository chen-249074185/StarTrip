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


async def test_replace_source_deletes_before_insert(monkeypatch):
    calls: list[tuple[str, tuple]] = []

    async def fake_execute(query, params):
        calls.append((query, params))

    monkeypatch.setattr(build_kb, "execute", fake_execute)
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
    inserts = [c for c in calls[1:] if c[0].startswith("INSERT INTO docs")]
    assert len(inserts) == 2
    assert inserts[0][1][0:3] == ("上海", "第一段", "kb/shanghai.md")
