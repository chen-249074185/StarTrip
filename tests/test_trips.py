"""行程落库：persist 节点 / PG 集成 / API / 鉴权隔离。"""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

import app.main as main_mod
from app.auth import create_access_token
from app.config import settings
from app.db.pg import close_pool, execute, init_schema, open_pool
from app.db.trips import get_trip, list_trips, save_trip
from app.main import app
from app.nodes import persist as persist_mod
from app.nodes.persist import persist

PLAN = {
    "days": [
        {"date": "D1", "spots": [{"name": "外滩"}, {"name": "豫园"}]},
    ]
}


def _pg_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=0.5):
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


async def test_persist_saves_trip(monkeypatch):
    monkeypatch.setattr(settings, "trip_persist_enabled", True)
    captured: dict = {}

    async def fake_save(session_id, title, plan, score):
        captured.update(
            {"session_id": session_id, "title": title, "plan": plan, "score": score}
        )
        return 7

    monkeypatch.setattr(persist_mod, "save_trip", fake_save)
    out = await persist(
        {
            "trip_plan": PLAN,
            "score": 88.0,
            "session_id": "1:s",
            "city": "上海",
        }
    )
    assert out == {"trip_id": 7}
    assert captured["session_id"] == "1:s"
    assert captured["title"] == "上海1日游"
    assert captured["score"] == 88.0


async def test_persist_skips_without_plan_or_disabled(monkeypatch):
    monkeypatch.setattr(settings, "trip_persist_enabled", True)
    assert await persist({"session_id": "s"}) == {}

    monkeypatch.setattr(settings, "trip_persist_enabled", False)
    assert (
        await persist({"session_id": "s", "trip_plan": PLAN, "score": 88.0}) == {}
    )


async def test_trips_api_list(monkeypatch):
    captured: dict = {}

    async def fake_list(session_id, limit):
        captured.update({"session_id": session_id, "limit": limit})
        return [
            {
                "id": 1,
                "title": "上海1日游",
                "score": 88.0,
                "days": 1,
                "created_at": datetime.now(UTC).isoformat(),
            }
        ]

    monkeypatch.setattr(main_mod, "list_trips", fake_list)
    resp = await get("/api/trips?session_id=s1&limit=5")
    assert resp.status_code == 200
    data = resp.json()["data"]["trips"]
    assert data[0]["title"] == "上海1日游"
    assert captured == {"session_id": "s1", "limit": 5}


async def test_trips_api_uses_user_namespace(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    captured: dict = {}

    async def fake_list(session_id, limit):
        captured["session_id"] = session_id
        return []

    monkeypatch.setattr(main_mod, "list_trips", fake_list)
    token = create_access_token("1")
    resp = await get(
        "/api/trips?session_id=s1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert captured["session_id"] == "1:s1"


async def test_trip_detail_returns_404_when_not_owned(monkeypatch):
    async def fake_get(trip_id, session_id):
        return None

    monkeypatch.setattr(main_mod, "get_trip", fake_get)
    resp = await get("/api/trips/1?session_id=s1")
    assert resp.status_code == 404


@pytest.mark.skipif(not _pg_up(), reason="PostgreSQL 未启动")
async def test_trip_pg_roundtrip():
    close_pool()
    open_pool()
    await init_schema()
    session_id = f"test-trip-{uuid4().hex[:8]}"
    try:
        trip_id = await save_trip(session_id, "上海1日游", PLAN, 88.0)
        rows = await list_trips(session_id)
        assert rows and rows[0]["id"] == trip_id
        assert rows[0]["days"] == 1
        assert rows[0]["score"] == 88.0

        detail = await get_trip(trip_id, session_id)
        assert detail is not None
        assert detail["trip_plan"]["days"][0]["spots"][0]["name"] == "外滩"

        assert await get_trip(trip_id, "other-session") is None
    finally:
        await execute("DELETE FROM trips WHERE session_id = %s", (session_id,))
        close_pool()
