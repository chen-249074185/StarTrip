"""混合检索：dense（pgvector 余弦）+ sparse（ILIKE 关键词）+ RRF 融合。"""

from __future__ import annotations

from pgvector import Vector

from app.config import settings
from app.db.pg import fetch
from app.llm import embed

# dense：余弦距离 <=>（越小越近）；只保留相似度 >= 阈值的结果
DENSE_SQL = """
SELECT id, content
FROM docs
WHERE 1 - (embedding <=> %s) >= %s
ORDER BY embedding <=> %s
LIMIT %s
"""


def _build_sparse_sql(n: int) -> str:
    """命中级数法 SQL（零依赖，无需 zhparser）。"""
    hits = " + ".join(["(CASE WHEN content ILIKE %s THEN 1 ELSE 0 END)"] * n)
    where = " OR ".join(["content ILIKE %s"] * n)
    return (
        f"SELECT id, content, ({hits}) AS hits FROM docs "
        f"WHERE {where} ORDER BY hits DESC LIMIT %s"
    )


async def dense_search(queries: list[str], topn: int = 20) -> list[int]:
    """多路 query 各召回（相似度低于阈值丢弃），保序去重合并。"""
    ids: list[int] = []
    thr = settings.rag_sim_threshold
    for q in queries:
        [emb] = await embed([q])
        vec = Vector(emb)
        rows = await fetch(DENSE_SQL, (vec, thr, vec, topn))
        ids.extend(r["id"] for r in rows)
    return list(dict.fromkeys(ids))


async def sparse_search(keywords: list[str], topn: int = 20) -> list[int]:
    kws = [w for w in keywords if w][:6]
    if not kws:
        return []
    like = [f"%{w}%" for w in kws]
    sql = _build_sparse_sql(len(kws))
    rows = await fetch(sql, (*like, *like, topn))
    return [r["id"] for r in rows]


def rrf(dense_ids: list[int], sparse_ids: list[int], k: int = 60, topk: int = 5) -> list[int]:
    """Reciprocal Rank Fusion：无需归一化、无需调权重。"""
    score: dict[int, float] = {}
    for ids in (dense_ids, sparse_ids):
        for rank, doc_id in enumerate(ids):
            score[doc_id] = score.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(score, key=score.get, reverse=True)[:topk]


async def fetch_contents(ids: list[int]) -> list[dict]:
    """按 id 取回原文（保序）。"""
    if not ids:
        return []
    rows = await fetch(
        "SELECT id, title, content, source FROM docs WHERE id = ANY(%s)", (ids,)
    )
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]
