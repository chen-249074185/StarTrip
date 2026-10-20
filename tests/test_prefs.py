"""偏好测试：Redis 读写/合并/降级、API、鉴权命名空间、prompt 注入。"""

from __future__ import annotations

import socket
from uuid import uuid4

import httpx
import pytest

import app.prefs as prefs_mod
from app.auth import create_access_token
from app.config import settings
from app.db.redis import close_redis, init_redis
from app.main import app
from app.nodes import planner as planner_mod
from app.nodes.planner import planner
from app.prefs import format_prefs, get_prefs, save_prefs


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttl: int | None = None

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value
        self.ttl = ex
        return True

    async def delete(self, key):
        self.data.pop(key, None)
        return 1


@pytest.fixture
def fake_redis(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(prefs_mod, "get_redis", lambda: client)
    return client


def _redis_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 6379), timeout=0.5):
            return True
    except OSError:
        return False


async def post(path: str, payload: dict, headers: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=payload, headers=headers or {})


async def get(path: str, headers: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers or {})


async def test_prefs_roundtrip_and_merge(fake_redis):
    assert await save_prefs("1:s", {"budget": 1000, "must_avoid": ["博物馆"]})
    assert await save_prefs("1:s", {"days": 2})
    data = await get_prefs("1:s")
    assert data["budget"] == 1000
    assert data["days"] == 2
    assert data["must_avoid"] == ["博物馆"]
    assert fake_redis.ttl == settings.pref_ttl_seconds
    assert format_prefs(data).startswith("预算 1000 元；天数 2")


async def test_prefs_invalid_stored_json(fake_redis):
    fake_redis.data["prefs:1:s"] = "{bad json"
    assert await get_prefs("1:s") == {}


async def test_prefs_degrades_without_redis(monkeypatch):
    monkeypatch.setattr(prefs_mod, "get_redis", lambda: None)
    assert await get_prefs("1:s") == {}
    assert await save_prefs("1:s", {"budget": 1}) is False


async def test_prefs_api_roundtrip(fake_redis):
    saved = await post(
        "/api/prefs",
        {"session_id": "s1", "prefs": {"budget": 1000}},
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["prefs"]["budget"] == 1000

    partial = await post(
        "/api/prefs",
        {"session_id": "s1", "prefs": {"days": 2}},
    )
    assert partial.status_code == 200
    assert partial.json()["data"]["prefs"]["budget"] == 1000
    assert partial.json()["data"]["prefs"]["days"] == 2

    fetched = await get("/api/prefs?session_id=s1")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["prefs"]["days"] == 2


async def test_prefs_api_uses_user_namespace(fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    token = create_access_token("1")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await post(
        "/api/prefs",
        {"session_id": "s1", "prefs": {"budget": 500}},
        headers=headers,
    )
    assert resp.status_code == 200
    assert "prefs:1:s1" in fake_redis.data


async def test_prefs_api_returns_503_without_redis(monkeypatch):
    monkeypatch.setattr(prefs_mod, "get_redis", lambda: None)
    resp = await post(
        "/api/prefs",
        {"session_id": "s1", "prefs": {"budget": 500}},
    )
    assert resp.status_code == 503


async def test_planner_injects_prefs(monkeypatch):
    captured: dict = {}

    async def fake_get_prefs(session_id):
        return {"budget": 1000, "must_avoid": ["博物馆"]}

    async def fake_chat(system, user, **kwargs):
        captured["user"] = user
        return '{"tasks": []}'

    monkeypatch.setattr(planner_mod, "get_prefs", fake_get_prefs)
    monkeypatch.setattr(planner_mod, "chat", fake_chat)

    await planner({"user_input": "上海两日游", "city": "上海", "session_id": "1:s"})
    assert "预算 1000 元" in captured["user"]
    assert "避开 博物馆" in captured["user"]


@pytest.mark.skipif(not _redis_up(), reason="Redis 未启动")
async def test_redis_roundtrip():
    client = await init_redis()
    assert client is not None
    thread_id = f"test-prefs-{uuid4().hex[:8]}"
    try:
        assert await save_prefs(thread_id, {"budget": 888})
        assert (await get_prefs(thread_id))["budget"] == 888
        await client.delete(f"prefs:{thread_id}")
    finally:
        await close_redis()
