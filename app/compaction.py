"""把工具结果 / 攻略压缩成“给 LLM 看的小抄”。

原始 MCP 结果又长又嵌套，直接 json.dumps(...)[:4000] 会切在 JSON 中间，
模型只能猜。这里按工具类型提取关键字段，并给每条内容设上限。
"""

from __future__ import annotations

from typing import Any

from app.grounding import extract_pois

# 景点搜索类工具：只保留模型真正需要的字段
_POI_TOOLS = ("maps_text_search", "maps_around_search")
_POI_FIELDS = ("name", "address", "distance", "type", "location")


def _compact_pois(results: Any, limit: int = 20) -> list[dict[str, Any]]:
    pois = extract_pois({"pois": results})
    rows: list[dict[str, Any]] = []
    for meta in pois.values():
        item = {key: meta.get(key) for key in _POI_FIELDS if meta.get(key) not in (None, "")}
        if item:
            rows.append(item)
        if len(rows) >= limit:
            break
    return rows


def _compact_texts(results: Any, limit: int = 5, max_chars: int = 800) -> list[str]:
    rows = results if isinstance(results, list) else [results]
    out: list[str] = []
    for row in rows[:limit]:
        if isinstance(row, str):
            out.append(row[:max_chars])
        elif isinstance(row, dict):
            if "error" in row:
                out.append(str(row["error"])[:max_chars])
            else:
                out.append(str(row)[:max_chars])
        else:
            out.append(str(row)[:max_chars])
    return out


def compact_tool_results(
    tool_results: dict[str, Any] | None,
    *,
    max_pois: int = 20,
    max_texts: int = 5,
    max_chars: int = 800,
) -> dict[str, Any]:
    """按工具类型压缩结果；未知工具退化为截断文本。"""
    compacted: dict[str, Any] = {}
    for tool, results in (tool_results or {}).items():
        if tool in _POI_TOOLS:
            compacted[tool] = _compact_pois(results, limit=max_pois)
        else:
            compacted[tool] = _compact_texts(
                results, limit=max_texts, max_chars=max_chars
            )
    return compacted


def compact_rag_hints(
    rag_hints: list[str] | None,
    *,
    limit: int = 5,
    max_chars: int = 500,
) -> list[str]:
    """攻略原文按条截断，保留来源感（每条形如“标题：内容”时不会被整段丢弃）。"""
    return [str(hint)[:max_chars] for hint in (rag_hints or [])[:limit]]
