
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from opentelemetry.trace import Span, Status, StatusCode
from pydantic import BaseModel

import app.graph as graph_module
from app.config import settings
from app.db.checkpoint import init_checkpointer
from app.db.pg import close_pool, init_schema, open_pool
from app.observability import (
    get_tracer,
    node_attributes,
    setup_tracing,
    shutdown_tracing,
    tracing_enabled,
)
from app.resilience import breaker_snapshot
from app.tools import close_amap


@asynccontextmanager
async def lifespan(_: FastAPI):
    tracing = setup_tracing()
    print(f"[startup] OTel tracing: {'on' if tracing else 'off'}")
    try:
        open_pool()
        await init_schema()
        checkpointer = await init_checkpointer()
        graph_module.set_checkpointer(checkpointer)
        print("[startup] Checkpoint 已启用（PostgresSaver）")
    except Exception as e:  # noqa: BLE001
        print(f"[startup] PG 未就绪，降级为内存 Checkpoint: {e}")
    yield
    await close_amap()   # 释放 MCP 会话
    close_pool()
    shutdown_tracing()


app = FastAPI(title="StarTrip Agent", version="0.1.0", lifespan=lifespan)

# 节点名 → (SSE 阶段, 开始提示)
NODE_STAGE = {
    "router": ("routing", "正在判断意图..."),
    "chat": ("chatting", "正在回复..."),
    "recommend": ("recommending", "正在挑选目的地..."),
    "planner": ("planning", "正在拆解任务..."),
    "executor": ("executing", "正在搜索景点（高德）..."),
    "retriever": ("rag", "正在检索攻略知识库..."),
    "reviewer": ("reviewing", "正在审查行程..."),
}


def node_summary(name: str, out: dict) -> dict:
    """把节点产出压成一句可展示的摘要，让前端看得出"这一步成功没有"。"""
    if name == "router":
        city = out.get("city") or ""
        return {"msg": f"意图：{out.get('intent')}" + (f"（目的地：{city}）" if city else "")}
    if name == "recommend":
        return {"msg": f"推荐了 {len(out.get('options', []))} 个目的地"}
    if name == "chat":
        return {"msg": "已回复"}
    if name == "planner":
        tasks = out.get("tasks", [])
        tools = "、".join(t.get("tool", "?") for t in tasks) or "（空）"
        return {"msg": f"任务拆解完成：{tools}", "tasks": tasks}
    if name == "executor":
        return {"msg": f"工具执行完成：{len(out.get('tool_results', {}))} 类结果"}
    if name == "retriever":
        return {"msg": f"检索到 {len(out.get('rag_hints', []))} 条攻略"}
    if name == "reviewer":
        score = out.get("score")
        fb = out.get("feedback")
        msg = f"评分 {score}"
        if fb:
            msg += f"（未达标，重新规划：{fb}）"
        return {"msg": msg, "score": score, "feedback": fb}
    return {}


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ResumeRequest(BaseModel):
    session_id: str
    tasks: list[dict] | None = None


def sse(event: str, data: dict) -> str:
    """格式化为 SSE 事件块。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def interrupt_payload(snapshot) -> dict | None:
    """从暂停态里取第一个 interrupt 的 value（HITL 任务清单）。"""
    if not getattr(snapshot, "next", ()):
        return None
    for task in getattr(snapshot, "tasks", ()) or ():
        for item in getattr(task, "interrupts", ()) or ():
            value = getattr(item, "value", None) or {}
            if isinstance(value, dict):
                return {
                    "tasks": value.get("tasks", []),
                    "msg": value.get("msg", "请确认任务清单"),
                }
    return None


TRACE_NODES = set(NODE_STAGE) | {"confirm", "remember"}


async def stream_graph(graph_input, config: dict):
    """跑图并转 SSE：有 interrupt 则暂停，否则推 result；同时记录 OTel span。"""
    final: dict = {}
    thread_id = str(config.get("configurable", {}).get("thread_id", ""))
    is_resume = isinstance(graph_input, Command)
    tracer = get_tracer()
    node_spans: dict[str, Span] = {}
    interrupted = False

    with tracer.start_as_current_span(
        "chat.resume" if is_resume else "chat.request"
    ) as span:
        span.set_attribute("session.id", thread_id)
        span.set_attribute("chat.is_resume", is_resume)
        span.set_attribute("hitl.enabled", settings.hitl_enabled)
        span.set_attribute("checkpoint.kind", graph_module.checkpointer_kind())
        try:
            async for ev in graph_module.graph.astream_events(
                graph_input, config, version="v2"
            ):
                name = ev.get("name")
                if name not in TRACE_NODES:
                    continue

                run_id = ev.get("run_id")
                if run_id and ev["event"] == "on_chain_start":
                    child = tracer.start_span(f"node.{name}")
                    child.set_attribute("node.name", name)
                    node_spans[run_id] = child
                elif run_id and ev["event"] == "on_chain_end":
                    child = node_spans.pop(run_id, None)
                    out = ev["data"].get("output")
                    if child is not None:
                        if isinstance(out, dict):
                            for key, value in node_attributes(name, out).items():
                                child.set_attribute(key, value)
                        child.set_attribute("node.status", "ok")
                        child.end()

                if name not in NODE_STAGE:
                    continue
                stage, start_msg = NODE_STAGE[name]
                if ev["event"] == "on_chain_start":
                    yield sse("progress", {"stage": stage, "msg": start_msg})
                elif ev["event"] == "on_chain_end":
                    out = ev["data"].get("output")
                    if isinstance(out, dict):
                        final.update(out)
                        yield sse("node", {"node": name, "stage": stage, **node_summary(name, out)})

            snapshot = await graph_module.graph.aget_state(config)
            payload = interrupt_payload(snapshot)
            if payload is not None:
                interrupted = True
                yield sse("interrupt", payload)
            else:
                score = final.get("score")
                span.set_attribute(
                    "run.score", float(score) if score is not None else 0.0
                )
                span.set_attribute("run.has_plan", bool(final.get("trip_plan")))
                span.set_attribute("run.reply_length", len(final.get("reply") or ""))
                yield sse("result", {
                    "trip_plan": final.get("trip_plan"),
                    "score": score,
                    "reply": final.get("reply"),
                    "options": final.get("options"),
                })
            yield sse("done", {})
        except Exception as e:  # noqa: BLE001
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR))
            yield sse("error", {"code": 500, "msg": str(e)})
            yield sse("done", {})
        finally:
            for child in node_spans.values():
                child.set_attribute(
                    "node.status", "interrupted" if interrupted else "incomplete"
                )
                child.end()
            span.set_attribute("run.interrupted", interrupted)


@app.get("/health")
async def health() -> dict:
    """健康检查：后续接入 PG / Redis / LLM / MCP 的真实探测。"""
    return {
        "status": "ok",
        "pg": "unknown",
        "redis": "unknown",
        "llm": "ok" if settings.deepseek_api_key else "unconfigured",
        "mcp": "unknown",
        "checkpoint": graph_module.checkpointer_kind(),
        "tracing": "on" if tracing_enabled() else "off",
        "breakers": breaker_snapshot(),
    }


@app.get("/api/config")
async def config() -> dict:
    """下发前端需要的公开配置（高德 JS key / 安全码）。"""
    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "amap_js_key": settings.amap_js_key,
            "amap_js_security_code": settings.amap_js_security_code,
        },
    }


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """SSE 流：跑 LangGraph 图，推 progress / node / interrupt / result。"""
    state_in = {"user_input": req.message, "session_id": req.session_id}
    config = {"configurable": {"thread_id": req.session_id}}
    return StreamingResponse(stream_graph(state_in, config), media_type="text/event-stream")


@app.post("/api/resume")
async def resume(req: ResumeRequest) -> StreamingResponse:
    """HITL 恢复：用确认/编辑后的任务清单继续跑同一 thread。"""
    config = {"configurable": {"thread_id": req.session_id}}
    command = Command(resume={"tasks": req.tasks or []})
    return StreamingResponse(stream_graph(command, config), media_type="text/event-stream")
