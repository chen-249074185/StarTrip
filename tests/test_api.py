"""API / SSE 测试：用假图覆盖正常流、HITL 暂停/恢复、错误流。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from langgraph.types import Command

import app.main as main_mod
from app.main import app


def _event(kind: str, name: str, run_id: str, output: dict | None = None) -> dict:
    data = {} if output is None else {"output": output}
    return {"event": kind, "name": name, "run_id": run_id, "data": data}


def _snapshot(*, next_: tuple = (), tasks: tuple = ()):
    return SimpleNamespace(next=next_, tasks=tasks)


def _interrupt_snapshot(tasks: list[dict]) -> SimpleNamespace:
    item = SimpleNamespace(
        interrupts=(SimpleNamespace(value={"tasks": tasks, "msg": "请确认"}),)
    )
    return _snapshot(next_=("confirm",), tasks=(item,))


class FakeGraph:
    def __init__(self, events: list[dict], snapshot):
        self.events = events
        self.snapshots = snapshot if isinstance(snapshot, list) else [snapshot]
        self.inputs: list[tuple] = []

    async def astream_events(self, graph_input, config, version="v2"):
        self.inputs.append((graph_input, config))
        for event in self.events:
            yield event

    async def aget_state(self, config):
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[0]


class BoomGraph:
    async def astream_events(self, graph_input, config, version="v2"):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    async def aget_state(self, config):
        return _snapshot()


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        event = "message"
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if data is not None:
            events.append((event, data))
    return events


async def post(path: str, payload: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=payload)


async def get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


NORMAL_EVENTS = [
    _event("on_chain_start", "router", "r1"),
    _event("on_chain_end", "router", "r1", {"intent": "plan", "city": "上海"}),
    _event("on_chain_start", "planner", "p1"),
    _event("on_chain_end", "planner", "p1", {"tasks": [{"tool": "maps_weather"}]}),
    _event("on_chain_start", "reviewer", "v1"),
    _event(
        "on_chain_end",
        "reviewer",
        "v1",
        {
            "trip_plan": {"days": [{"date": "D1", "spots": [{"name": "外滩"}]}]},
            "score": 88.0,
            "reply": "已安排",
            "feedback": None,
        },
    ),
]


async def test_chat_sse_normal(monkeypatch):
    fake = FakeGraph(NORMAL_EVENTS, _snapshot())
    monkeypatch.setattr(main_mod.graph_module, "graph", fake)

    resp = await post("/api/chat", {"session_id": "s1", "message": "上海两日游"})
    assert resp.status_code == 200
    events = parse_sse(resp.text)
    names = [name for name, _ in events]
    assert "progress" in names
    assert "node" in names
    assert "result" in names
    assert names[-1] == "done"
    result = dict(events)["result"]
    assert result["score"] == 88.0
    assert result["trip_plan"]["days"][0]["spots"][0]["name"] == "外滩"


async def test_chat_sse_interrupt(monkeypatch):
    tasks = [{"tool": "maps_text_search", "args": {"city": "上海"}}]
    fake = FakeGraph(NORMAL_EVENTS[:2], _interrupt_snapshot(tasks))
    monkeypatch.setattr(main_mod.graph_module, "graph", fake)

    resp = await post("/api/chat", {"session_id": "s2", "message": "上海两日游"})
    events = parse_sse(resp.text)
    names = [name for name, _ in events]
    assert "interrupt" in names
    assert "result" not in names
    interrupt = dict(events)["interrupt"]
    assert interrupt["tasks"] == tasks
    assert interrupt["msg"] == "请确认"


async def test_resume_passes_tasks(monkeypatch):
    tasks = [{"tool": "maps_weather", "args": {"city": "上海"}}]
    fake = FakeGraph(NORMAL_EVENTS[4:], [_interrupt_snapshot(tasks), _snapshot()])
    monkeypatch.setattr(main_mod.graph_module, "graph", fake)

    resp = await post("/api/resume", {"session_id": "s3", "tasks": tasks})
    events = parse_sse(resp.text)
    assert dict(events)["result"]["score"] == 88.0
    names = [name for name, _ in events]
    assert names[-1] == "done"
    graph_input = fake.inputs[0][0]
    assert isinstance(graph_input, Command)
    assert graph_input.resume["tasks"] == tasks


async def test_resume_without_pending_interrupt(monkeypatch):
    monkeypatch.setattr(main_mod.graph_module, "graph", FakeGraph([], _snapshot()))
    resp = await post("/api/resume", {"session_id": "s6", "tasks": []})
    assert resp.status_code == 404


async def test_chat_error_event(monkeypatch):
    monkeypatch.setattr(main_mod.graph_module, "graph", BoomGraph())
    resp = await post("/api/chat", {"session_id": "s4", "message": "hi"})
    events = parse_sse(resp.text)
    assert dict(events)["error"]["msg"] == "boom"
    assert events[-1][0] == "done"


async def test_health_and_config():
    health = await get("/health")
    assert health.status_code == 200
    body = health.json()
    for key in (
        "status",
        "pg",
        "redis",
        "llm",
        "mcp",
        "checkpoint",
        "tracing",
        "auth",
        "breakers",
    ):
        assert key in body

    config = await get("/api/config")
    assert config.status_code == 200
    data = config.json()
    assert data["code"] == 0
    assert "amap_js_key" in data["data"]
    assert "amap_js_security_code" in data["data"]
    assert "auth_enabled" in data["data"]


@pytest.mark.parametrize(
    "events, expected",
    [
        (NORMAL_EVENTS, "result"),
        (NORMAL_EVENTS[:2], "progress"),
    ],
)
async def test_event_parsing_smoke(monkeypatch, events, expected):
    snapshot = _snapshot() if expected == "result" else _interrupt_snapshot([])
    monkeypatch.setattr(main_mod.graph_module, "graph", FakeGraph(events, snapshot))
    resp = await post("/api/chat", {"session_id": "s5", "message": "x"})
    assert expected in [name for name, _ in parse_sse(resp.text)]
