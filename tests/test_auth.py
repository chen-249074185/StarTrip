"""鉴权单测：密码 / JWT / 依赖 / 登录 / 401 / session 隔离。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import JWTError, jwt

import app.main as main_mod
from app.auth import (
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    thread_id_for,
    verify_password,
)
from app.config import settings
from app.main import app

EVENTS = [
    {"event": "on_chain_start", "name": "router", "run_id": "r1", "data": {}},
    {
        "event": "on_chain_end",
        "name": "router",
        "run_id": "r1",
        "data": {"output": {"intent": "chat", "city": ""}},
    },
    {"event": "on_chain_start", "name": "chat", "run_id": "c1", "data": {}},
    {
        "event": "on_chain_end",
        "name": "chat",
        "run_id": "c1",
        "data": {"output": {"reply": "hi", "options": []}},
    },
]


class CaptureGraph:
    def __init__(self):
        self.configs: list[dict] = []

    async def astream_events(self, graph_input, config, version="v2"):
        self.configs.append(config)
        for event in EVENTS:
            yield event

    async def aget_state(self, config):
        return SimpleNamespace(next=(), tasks=())


class IsolationGraph:
    async def aget_state(self, config):
        thread_id = config["configurable"]["thread_id"]
        if thread_id == "1:s":
            item = SimpleNamespace(
                interrupts=(SimpleNamespace(value={"tasks": [], "msg": "确认"}),)
            )
            return SimpleNamespace(next=("confirm",), tasks=(item,))
        return SimpleNamespace(next=(), tasks=())

    async def astream_events(self, graph_input, config, version="v2"):
        if False:  # pragma: no cover
            yield {}


async def post(path: str, payload: dict, headers: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=payload, headers=headers or {})


def test_password_hash_roundtrip():
    stored = hash_password("secret123")
    assert stored.startswith("scrypt$")
    assert verify_password("secret123", stored) is True
    assert verify_password("wrong", stored) is False


def test_jwt_roundtrip(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    token = create_access_token("42")
    assert decode_access_token(token) == "42"


def test_jwt_invalid_and_expired(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    with pytest.raises(JWTError):
        decode_access_token("not-a-token")

    expired = jwt.encode(
        {
            "sub": "1",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        "test-secret",
        algorithm="HS256",
    )
    with pytest.raises(JWTError):
        decode_access_token(expired)


def test_thread_id_isolation():
    assert thread_id_for("1", "s") == "1:s"
    assert thread_id_for("1", "s") != thread_id_for("2", "s")
    assert thread_id_for(None, "s") == "s"


async def test_get_current_user_disabled(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    assert await get_current_user(None) is None


async def test_get_current_user_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    with pytest.raises(HTTPException) as exc:
        await get_current_user(None)
    assert exc.value.status_code == 401

    cred = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=create_access_token("7")
    )
    assert await get_current_user(cred) == "7"


async def test_login_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")

    async def fake_auth(username, password):
        if username == "admin" and password == "pw123456":
            return {"id": 1, "username": "admin"}
        return None

    monkeypatch.setattr(main_mod, "authenticate_user", fake_auth)

    ok = await post(
        "/api/auth/login", {"username": "admin", "password": "pw123456"}
    )
    assert ok.status_code == 200
    token = ok.json()["data"]["access_token"]
    assert decode_access_token(token) == "1"

    bad = await post("/api/auth/login", {"username": "admin", "password": "bad"})
    assert bad.status_code == 401


async def test_login_disabled(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    resp = await post("/api/auth/login", {"username": "a", "password": "b"})
    assert resp.status_code == 400


async def test_chat_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    resp = await post("/api/chat", {"session_id": "s", "message": "hi"})
    assert resp.status_code == 401


async def test_chat_uses_user_namespace(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    graph = CaptureGraph()
    monkeypatch.setattr(main_mod.graph_module, "graph", graph)

    resp = await post(
        "/api/chat",
        {"session_id": "s", "message": "hi"},
        headers={"Authorization": f"Bearer {create_access_token('1')}"},
    )
    assert resp.status_code == 200
    assert graph.configs[0]["configurable"]["thread_id"] == "1:s"


async def test_wrong_user_cannot_resume(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "jwt_secret", "test-secret")
    monkeypatch.setattr(main_mod.graph_module, "graph", IsolationGraph())

    resp = await post(
        "/api/resume",
        {"session_id": "s", "tasks": []},
        headers={"Authorization": f"Bearer {create_access_token('2')}"},
    )
    assert resp.status_code == 404
