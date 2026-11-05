"""RAG 节点：查询改写 → 混合检索（dense+sparse）→ RRF → topK 原文。"""

from __future__ import annotations

import asyncio
import json
import logging

from app.rag.rewrite import rewrite
from app.rag.search import dense_search, fetch_contents, rrf, sparse_search
from app.state import TripState

TOPK = 5
logger = logging.getLogger(__name__)


def _extract_spots(tool_results: dict) -> list[str]:
    """从高德 POI 结果里尽力提取景点名（MCP 返回的是 JSON 文本）。"""
    names: list[str] = []
    for item in tool_results.get("maps_text_search", []):
        payloads = item if isinstance(item, list) else [item]
        for p in payloads:
            if not isinstance(p, str):
                continue
            try:
                data = json.loads(p)
            except Exception:
                logger.debug("跳过无法解析的工具结果", exc_info=True)
                continue
            for poi in data.get("pois", []):
                name = poi.get("name")
                if name:
                    names.append(name)
    return names


async def retriever(state: TripState) -> dict:
    user_input = state.get("user_input", "")
    spots = _extract_spots(state.get("tool_results", {}))

    rw = await rewrite(user_input, spots, state.get("city", ""))
    dense_ids, sparse_ids = await asyncio.gather(
        dense_search(rw["dense_queries"]),
        sparse_search(rw["keywords"]),
    )
    fused = rrf(dense_ids, sparse_ids, topk=TOPK)
    rows = await fetch_contents(fused)
    return {"rag_hints": [r["content"] for r in rows]}
