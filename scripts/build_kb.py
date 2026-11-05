"""离线构建知识库：读取目录下的 .md → 切块 → embedding → 写入 docs 表。

用法：
    python -m scripts.build_kb                 # 默认读 data/kb
    python -m scripts.build_kb scripts/sample_kb
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from pgvector import Vector

from app.db.pg import close_pool, execute, init_schema, open_pool
from app.llm import embed

CHUNK_SIZE = 512
CHUNK_OVERLAP = 50


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """定长切块（带重叠，防切断语义）。"""
    step = size - overlap
    chunks = []
    for i in range(0, len(text), step):
        chunks.append(text[i : i + size])
        if i + size >= len(text):
            break
    return [c for c in chunks if c.strip()]


def _title(text: str, fallback: str = "") -> str:
    return text.strip() or fallback


async def replace_source(
    source: str,
    title: str,
    chunks: list[str],
    embs: list[list[float]],
) -> int:
    """同一来源先删后插：重复执行不会产生重复块（幂等重建）。"""
    await execute("DELETE FROM docs WHERE source = %s", (source,))
    for chunk, e in zip(chunks, embs, strict=True):
        await execute(
            "INSERT INTO docs (title, content, source, embedding) VALUES (%s, %s, %s, %s)",
            (title, chunk, source, Vector(e)),
        )
    return len(chunks)


async def main(kb_dir: Path) -> None:
    open_pool()
    try:
        await init_schema()

        files = sorted(kb_dir.glob("*.md")) if kb_dir.exists() else []
        if not files:
            print(f"未找到知识库文件（{kb_dir}），请放入 .md 后重试")
            return

        total = 0
        for f in files:
            text = f.read_text(encoding="utf-8")
            # title 取首行标题去掉 # 与"旅游攻略"，即中文城市名（如 北京）
            title = _title(
                text.splitlines()[0].lstrip("# ").replace("旅游攻略", ""),
                f.stem,
            )
            chunks = chunk_text(text)
            if not chunks:
                continue
            embs = await embed(chunks)
            total += await replace_source(str(f), title, chunks, embs)
            print(f"{f.name}: {len(chunks)} chunks")
        print(f"完成，共写入 {total} 条")
    finally:
        close_pool()


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "kb"
    asyncio.run(main(Path(arg)))
