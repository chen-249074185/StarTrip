"""OpenTelemetry 可观测：trace 初始化 + 节点属性映射。

- `OTEL_ENABLED=true` 时导出到 OTLP gRPC（默认 Jaeger :4317）
- 未开启时全部使用 OTel 的 no-op tracer，业务零感知
- 节点 span 由 `/api/chat` 的 SSE 事件驱动创建：on_chain_start → start，on_chain_end → end
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import settings

_provider: TracerProvider | None = None
_tracer: trace.Tracer | None = None
_configured = False


def setup_tracing(enabled: bool | None = None) -> bool:
    """初始化 tracer provider；返回是否真正启用了导出。"""
    global _provider, _tracer, _configured
    if _configured:
        return _provider is not None
    _configured = True

    if enabled is None:
        enabled = settings.otel_enabled
    if not enabled:
        return False

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.otel_service_name})
    )
    exporter = OTLPSpanExporter(
        endpoint=settings.otel_endpoint,
        insecure=settings.otel_insecure,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _provider = provider
    _tracer = trace.get_tracer("startrip")
    return True


def shutdown_tracing() -> None:
    """应用关闭前 flush，避免批处理队列里的 span 丢失。"""
    global _provider, _tracer, _configured
    if _provider is not None:
        _provider.force_flush()
        _provider.shutdown()
    _provider = None
    _tracer = None
    _configured = False


def tracing_enabled() -> bool:
    return _provider is not None


def get_tracer() -> trace.Tracer:
    return _tracer or trace.get_tracer("startrip")


def node_attributes(name: str, out: dict) -> dict[str, Any]:
    """按节点类型提炼少量可查询属性（避免把整个状态塞进 span）。"""
    attrs: dict[str, Any] = {}
    if name == "router":
        attrs["intent"] = out.get("intent") or ""
        attrs["destination.city"] = out.get("city") or ""
    elif name == "planner":
        tasks = out.get("tasks") or []
        attrs["plan.task_count"] = len(tasks)
        attrs["plan.tools"] = ",".join(str(t.get("tool")) for t in tasks)
    elif name == "executor":
        results = out.get("tool_results") or {}
        attrs["tool.group_count"] = len(results)
        attrs["tool.result_count"] = sum(
            len(v) for v in results.values() if isinstance(v, list)
        )
    elif name == "retriever":
        attrs["rag.hint_count"] = len(out.get("rag_hints") or [])
    elif name == "reviewer":
        attrs["review.score"] = float(out.get("score") or 0)
        attrs["review.has_feedback"] = bool(out.get("feedback"))
    elif name == "confirm":
        attrs["hitl.task_count"] = len(out.get("tasks") or [])
    elif name == "remember":
        attrs["memory.history_count"] = len(out.get("history") or [])
    return attrs
