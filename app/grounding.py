"""行程接地（grounding）与通勤时间估算。

LLM 生成行程时最容易犯的错是“编一个不存在的景点”。这里把
“每个景点能不能在工具结果 / 攻略里找到依据”做成确定性检查，
并把 POI 坐标换算成相邻景点间的驾车时间，让 validate_plan 的
travel_times 检查真正生效（而不是永远收到空字典）。
"""

from __future__ import annotations

import json
import math
import re
from itertools import pairwise
from typing import Any

from app.plan import normalize_plan

# 常见景点后缀：只在名称较长时去掉，避免把“山”“湖”这类单字误伤
_SPOT_SUFFIXES = (
    "风景区",
    "旅游景区",
    "旅游区",
    "景区",
    "公园",
    "博物馆",
    "纪念馆",
    "步行街",
    "古镇",
    "古城",
    "广场",
    "中心",
)

_NORM_RE = re.compile(r"[\s·・,，.。;；:：()（）\[\]【】\-—_/\\]+")


def _norm(text: Any) -> str:
    return _NORM_RE.sub("", str(text or "")).lower()


def _aliases(name: Any) -> set[str]:
    """名称归一化 + 去掉常见后缀，用于宽松但可控的匹配。"""
    base = _norm(name)
    if not base:
        return set()
    out = {base}
    for suffix in _SPOT_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix) + 1:
            out.add(base[: -len(suffix)])
    return {item for item in out if len(item) >= 2}


def _name_matches(left: Any, right: Any) -> bool:
    left_aliases = _aliases(left)
    right_aliases = _aliases(right)
    if not left_aliases or not right_aliases:
        return False
    for a in left_aliases:
        for b in right_aliases:
            if a == b or a in b or b in a:
                return True
    return False


def _walk_payload(payload: Any, out: dict[str, dict[str, Any]]) -> None:
    """递归解析 MCP 返回的各种形状：JSON 字符串 / dict / list。"""
    if isinstance(payload, dict):
        pois = payload.get("pois")
        if isinstance(pois, list):
            for poi in pois:
                _add_poi(poi, out)
            return
        if payload.get("name"):
            _add_poi(payload, out)
            return
        for value in payload.values():
            _walk_payload(value, out)
        return
    if isinstance(payload, (list, tuple)):
        for value in payload:
            _walk_payload(value, out)
        return
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith(("{", "[")):
            try:
                _walk_payload(json.loads(text), out)
            except (ValueError, TypeError):
                return


def _add_poi(poi: Any, out: dict[str, dict[str, Any]]) -> None:
    if not isinstance(poi, dict):
        return
    name = str(poi.get("name") or "").strip()
    if not name:
        return
    location = poi.get("location")
    coords: tuple[float, float] | None = None
    if isinstance(location, str) and "," in location:
        try:
            lng_text, lat_text = location.split(",", 1)
            coords = (float(lng_text), float(lat_text))
        except (TypeError, ValueError):
            coords = None
    elif isinstance(location, (list, tuple)) and len(location) >= 2:
        try:
            coords = (float(location[0]), float(location[1]))
        except (TypeError, ValueError):
            coords = None
    existing = out.get(name)
    if existing is not None and existing.get("location") is not None:
        return
    out[name] = {
        "name": name,
        "address": str(poi.get("address") or "")[:200],
        "location": coords,
        "type": str(poi.get("type") or "")[:100],
    }


def extract_pois(tool_results: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """从工具结果里提取 `景点名 -> {address, location, type}`。"""
    pois: dict[str, dict[str, Any]] = {}
    for payload in (tool_results or {}).values():
        _walk_payload(payload, pois)
    return pois


def _find_coords(
    name: str, pois: dict[str, dict[str, Any]]
) -> tuple[float, float] | None:
    if name in pois:
        return pois[name].get("location")
    for candidate, meta in pois.items():
        if _name_matches(name, candidate) and meta.get("location"):
            return meta["location"]
    return None


def _haversine_km(left: tuple[float, float], right: tuple[float, float]) -> float:
    lng1, lat1 = left
    lng2, lat2 = right
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def estimate_travel_times(
    plan: Any,
    pois: dict[str, dict[str, Any]] | None = None,
    *,
    speed_kmh: float = 18.0,
) -> dict[tuple[str, str], int]:
    """用 POI 坐标估算同一天相邻景点的驾车时间（分钟）。

    没有真实路线数据时用直线距离 / 城市平均车速 + 5 分钟缓冲。它是保守估算，
    只用于触发“时间间隔明显不够”的确定性校验，不参与展示给用户的精确导航。
    """
    normalized = normalize_plan(plan)
    speed = max(1.0, float(speed_kmh))
    travel: dict[tuple[str, str], int] = {}
    for day in normalized.get("days") or []:
        spots = [
            str(spot.get("name") or "").strip()
            for spot in day.get("spots") or []
            if str(spot.get("name") or "").strip()
        ]
        for prev_name, next_name in pairwise(spots):
            if prev_name == next_name:
                continue
            prev_coords = _find_coords(prev_name, pois or {})
            next_coords = _find_coords(next_name, pois or {})
            if prev_coords is None or next_coords is None:
                continue
            km = _haversine_km(prev_coords, next_coords)
            minutes = max(5, round(km / speed * 60) + 5)
            travel[(prev_name, next_name)] = minutes
    return travel


def ground_plan(
    plan: Any,
    tool_results: dict[str, Any] | None = None,
    rag_hints: list[str] | None = None,
) -> dict[str, Any]:
    """检查行程里的每个景点能否在工具结果或攻略原文中找到依据。

    返回结构固定，便于 SSE / 落库 / 评测复用：
    {applicable, total, grounded, ungrounded, ratio}
    """
    normalized = normalize_plan(plan)
    names = [
        str(spot.get("name") or "").strip()
        for day in normalized.get("days") or []
        for spot in day.get("spots") or []
        if str(spot.get("name") or "").strip()
    ]
    pois = extract_pois(tool_results)
    rag_text = _norm(" ".join(str(hint) for hint in (rag_hints or [])))
    applicable = bool(pois or rag_text)

    grounded: list[str] = []
    ungrounded: list[str] = []
    for name in names:
        hit = any(_name_matches(name, candidate) for candidate in pois)
        if not hit and rag_text:
            hit = any(alias in rag_text for alias in _aliases(name))
        if hit:
            grounded.append(name)
        else:
            ungrounded.append(name)

    total = len(names)
    ratio = (
        round(len(ungrounded) / total, 4) if total and applicable else 0.0
    )
    return {
        "applicable": applicable,
        "total": total,
        "grounded": len(grounded),
        "ungrounded": ungrounded,
        "ratio": ratio,
    }
