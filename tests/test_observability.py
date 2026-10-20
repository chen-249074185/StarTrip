"""可观测单测：节点属性 / LLM token / 工具 span。"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app import llm, observability
from app.nodes import executor as executor_mod
from app.observability import node_attributes
from app.resilience import reset_breakers


@pytest.fixture
def spans(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability, "_tracer", provider.get_tracer("test"))
    yield exporter
    provider.shutdown()


def test_node_attributes():
    router = node_attributes("router", {"intent": "plan", "city": "上海"})
    assert router["intent"] == "plan"
    assert router["destination.city"] == "上海"

    planner = node_attributes(
        "planner", {"tasks": [{"tool": "a"}, {"tool": "b"}]}
    )
    assert planner["plan.task_count"] == 2
    assert planner["plan.tools"] == "a,b"

    executor = node_attributes(
        "executor", {"tool_results": {"weather": [1, 2], "poi": [3]}}
    )
    assert executor["tool.group_count"] == 2
    assert executor["tool.result_count"] == 3

    reviewer = node_attributes("reviewer", {"score": 88.5, "feedback": "太赶"})
    assert reviewer["review.score"] == 88.5
    assert reviewer["review.has_feedback"] is True


async def test_llm_chat_records_tokens(spans, monkeypatch):
    class Usage:
        prompt_tokens = 12
        completion_tokens = 7

    class Message:
        content = "ok"

    class Choice:
        message = Message()

    class Response:
        choices = (Choice(),)
        usage = Usage()

    class Completions:
        async def create(self, **kwargs):
            return Response()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    monkeypatch.setattr(llm, "_llm_client", lambda: Client())

    assert await llm._chat_once("deepseek-chat", [], {}) == "ok"
    finished = spans.get_finished_spans()
    assert len(finished) == 1
    span = finished[0]
    assert span.name == "llm.chat"
    assert span.attributes["gen_ai.request.model"] == "deepseek-chat"
    assert span.attributes["gen_ai.usage.input_tokens"] == 12
    assert span.attributes["gen_ai.usage.output_tokens"] == 7
    assert span.attributes["gen_ai.usage.total_tokens"] == 19


async def test_tool_span_records_status(spans, monkeypatch):
    reset_breakers()

    async def fake_tool(args):
        return ["ok"]

    monkeypatch.setattr(executor_mod, "get_tool", lambda name: fake_tool)

    result = await executor_mod.call_tool_safe(
        {"tool": "maps_weather", "args": {"city": "上海"}}
    )
    assert result == ["ok"]
    span = spans.get_finished_spans()[-1]
    assert span.name == "tool.maps_weather"
    assert span.attributes["tool.name"] == "maps_weather"
    assert span.attributes["tool.status"] == "ok"


def test_setup_tracing_disabled(monkeypatch):
    monkeypatch.setattr(observability, "_configured", False)
    monkeypatch.setattr(observability, "_provider", None)
    assert observability.setup_tracing(enabled=False) is False
    assert observability.tracing_enabled() is False
