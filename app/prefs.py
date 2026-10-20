"""用户偏好：模型 + Redis 读写 + prompt 格式化。

Key: `prefs:{thread_id}`（thread_id 已含 user_id 命名空间）
Value: JSON 字符串，TTL 默认 7 天
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.config import settings
from app.db.redis import get_redis


class Prefs(BaseModel):
    budget: int | None = Field(None, ge=0, le=1_000_000)
    days: int | None = Field(None, ge=1, le=30)
    pace: str | None = Field(None, max_length=32)
    transport: str | None = Field(None, max_length=32)
    interests: list[str] = Field(default_factory=list, max_length=20)
    must_include: list[str] = Field(default_factory=list, max_length=20)
    must_avoid: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field("", max_length=500)


def _key(thread_id: str) -> str:
    return f"prefs:{thread_id}"


async def get_prefs(thread_id: str) -> dict:
    client = get_redis()
    if client is None or not thread_id:
        return {}
    try:
        raw = await client.get(_key(thread_id))
    except Exception:  # noqa: BLE001
        return {}
    if not raw:
        return {}
    try:
        return Prefs.model_validate(json.loads(raw)).model_dump(exclude_none=True)
    except Exception:  # noqa: BLE001
        return {}


async def save_prefs(thread_id: str, prefs: dict) -> bool:
    """增量更新（只覆盖传入的非 None 字段），保留其他已有偏好。"""
    client = get_redis()
    if client is None or not thread_id:
        return False
    current = await get_prefs(thread_id)
    merged = {**current, **{k: v for k, v in prefs.items() if v is not None}}
    try:
        data = Prefs.model_validate(merged).model_dump(exclude_none=True)
        await client.set(
            _key(thread_id),
            json.dumps(data, ensure_ascii=False),
            ex=settings.pref_ttl_seconds,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def format_prefs(prefs: dict) -> str:
    """给 planner/reviewer 注入的一行偏好文本。"""
    parts: list[str] = []
    if prefs.get("budget") is not None:
        parts.append(f"预算 {prefs['budget']} 元")
    if prefs.get("days") is not None:
        parts.append(f"天数 {prefs['days']}")
    if prefs.get("pace"):
        parts.append(f"节奏 {prefs['pace']}")
    if prefs.get("transport"):
        parts.append(f"交通 {prefs['transport']}")
    if prefs.get("interests"):
        parts.append("兴趣 " + "、".join(prefs["interests"]))
    if prefs.get("must_include"):
        parts.append("必去 " + "、".join(prefs["must_include"]))
    if prefs.get("must_avoid"):
        parts.append("避开 " + "、".join(prefs["must_avoid"]))
    if prefs.get("notes"):
        parts.append(f"备注 {prefs['notes']}")
    return "；".join(parts)
