"""RAG 节点：查询改写 → 混合检索（dense+sparse）→ RRF → topK 原文。

可靠性：
- 检索失败不拖垮整张图：返回空 hints + rag_degraded，reviewer 会标注“未验证”
- 同一轮重规划复用第一次结果：用 (user_input, city, spots) 做缓存键
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging

from app.grounding import extract_pois
from app.rag.rewrite import rewrite
from app.rag.search import dense_search, fetch_contents, rrf, sparse_search
from app.state import TripState

TOPK = 5
MAX_HINT_CHARS = 800
logger = logging.getLogger(__name__)


def _extract_spots(tool_results: dict) -> list[str]:
    """从高德 POI 结果里提取景点名（复用 grounding 的解析逻辑）。"""
    return list(extract_pois(tool_results))[:12]


def _cache_key(user_input: str, city: str, spots: list[str]) -> str:
    raw = json.dumps(
        [user_input, city, sorted(spots)], ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


async def retriever(state: TripState) -> dict:
    user_input = state.get("user_input", "")
    city = state.get("city", "")
    spots = _extract_spots(state.get("tool_results", {}))
    key = _cache_key(user_input, city, spots)

    # 同一轮的重规划：工具结果没变就复用，避免 3 次 rewrite + embedding + 检索
    if state.get("rag_key") == key and state.get("rag_hints") is not None:
        return {}

    try:
        rw = await rewrite(user_input, spots, city)
        dense_ids, sparse_ids = await asyncio.gather(
            dense_search(rw["dense_queries"]),
            sparse_search(rw["keywords"]),
        )
        fused = rrf(dense_ids, sparse_ids, topk=TOPK)
        rows = await fetch_contents(fused)
        hints = [str(row.get("content") or "")[:MAX_HINT_CHARS] for row in rows]
        return {"rag_hints": hints, "rag_key": key, "rag_degraded": False}
    except Exception as e:  # noqa: BLE001
        logger.warning("RAG 检索失败，降级为空证据: %s", e)
        return {"rag_hints": [], "rag_key": key, "rag_degraded": True}
