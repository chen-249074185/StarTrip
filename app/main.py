import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command
from opentelemetry.trace import Span, Status, StatusCode
from pydantic import BaseModel, Field

import app.graph as graph_module
from app.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    thread_id_for,
)
from app.config import settings
from app.db.checkpoint import init_checkpointer
from app.db.pg import close_pool, fetch, init_schema, open_pool
from app.db.redis import close_redis, init_redis, redis_ready
from app.db.trips import get_trip, list_trips
from app.locks import get_lock, release, try_acquire
from app.observability import (
    get_tracer,
    node_attributes,
    setup_tracing,
    shutdown_tracing,
    tracing_enabled,
)
from app.plan import plan_is_usable
from app.prefs import Prefs, get_prefs, save_prefs
from app.resilience import breaker_snapshot
from app.session import new_session_id, sign_session
from app.tasks import sanitize_tasks
from app.tools import all_tool_names, amap_ready, close_amap, warm_up_amap


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auth_enabled and not settings.jwt_secret:
        raise RuntimeError("AUTH_ENABLED=true 但 JWT_SECRET 未配置")
    if not settings.auth_enabled:
        print("[startup] 警告：AUTH_ENABLED=false，仅适合本地/演示；公网请开启鉴权或 REQUIRE_SIGNED_SESSION")
    if settings.require_signed_session and not (
        settings.session_secret or settings.jwt_secret
    ):
        print("[startup] 警告：REQUIRE_SIGNED_SESSION=true 但 SESSION_SECRET/JWT_SECRET 为空，使用开发默认密钥")
    tracing = setup_tracing()
    print(f"[startup] OTel tracing: {'on' if tracing else 'off'}")
    try:
        await asyncio.to_thread(open_pool)
        await init_schema()
        checkpointer = await init_checkpointer()
        graph_module.set_checkpointer(checkpointer)
        print("[startup] Checkpoint 已启用（PostgresSaver）")
    except Exception as e:  # noqa: BLE001
        print(f"[startup] PG 未就绪，降级为内存 Checkpoint: {e}")
    redis_client = await init_redis()
    print(f"[startup] Redis: {'on' if redis_client else 'off'}")
    # MCP 冷启动放到后台预热：不阻塞 Web 启动，也避免第一个用户请求撞上 npx 启动超时
    warm_task = asyncio.create_task(warm_up_amap())
    try:
        yield
    finally:
        if not warm_task.done():
            warm_task.cancel()
            await asyncio.gather(warm_task, return_exceptions=True)
        await close_amap()   # 释放 MCP 会话
        await close_redis()
        close_pool()
        shutdown_tracing()


app = FastAPI(title="StarTrip Agent", version="0.2.0", lifespan=lifespan)

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
        degraded = out.get("rag_degraded")
        if degraded:
            return {"msg": "攻略检索失败，本轮不使用 RAG 证据"}
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
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)


class ResumeRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    tasks: list[dict] | None = Field(default=None, max_length=12)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PrefsRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    prefs: Prefs


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


TRACE_NODES = set(NODE_STAGE) | {"confirm", "remember", "persist"}
HEARTBEAT = ": ping\n\n"


def result_status(
    plan: dict | None,
    validation: dict | None,
    grounding: dict | None,
    *,
    cancelled: bool,
) -> str:
    if cancelled:
        return "cancelled"
    if plan_is_usable(plan):
        if validation and not validation.get("ok", True):
            return "degraded"
        if grounding and not grounding.get("applicable", True):
            return "degraded"
        if (
            grounding
            and grounding.get("applicable")
            and grounding.get("ratio", 0.0) > settings.grounding_max_ungrounded_ratio
        ):
            return "degraded"
        return "ok"
    return "degraded" if plan else "ok"


async def stream_graph(
    graph_input,
    config: dict,
    request: Request | None = None,
):
    """跑图并转 SSE：有 interrupt 则暂停，否则推 result；同时记录 OTel span。"""
    final: dict = {}
    thread_id = str(config.get("configurable", {}).get("thread_id", ""))
    is_resume = isinstance(graph_input, Command)
    tracer = get_tracer()
    node_spans: dict[str, Span] = {}
    interrupted = False

    lock = get_lock(thread_id)
    if not await try_acquire(lock):
        yield sse("error", {"code": 409, "msg": "该会话正在处理中，请稍后再试"})
        yield sse("done", {})
        return

    try:
        with tracer.start_as_current_span(
            "chat.resume" if is_resume else "chat.request"
        ) as span:
            span.set_attribute("session.id", thread_id)
            span.set_attribute("chat.is_resume", is_resume)
            span.set_attribute("hitl.enabled", settings.hitl_enabled)
            span.set_attribute("checkpoint.kind", graph_module.checkpointer_kind())
            next_task: asyncio.Task | None = None
            try:
                agen = graph_module.graph.astream_events(
                    graph_input, config, version="v2"
                ).__aiter__()
                next_task = asyncio.create_task(anext(agen))
                while True:
                    done, _ = await asyncio.wait(
                        {next_task}, timeout=settings.sse_heartbeat_seconds
                    )
                    if not done:
                        yield HEARTBEAT
                        if request is not None and await request.is_disconnected():
                            next_task.cancel()
                            await asyncio.gather(next_task, return_exceptions=True)
                            await agen.aclose()
                            return
                        continue
                    try:
                        ev = next_task.result()
                    except StopAsyncIteration:
                        break
                    next_task = asyncio.create_task(anext(agen))

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
                values = getattr(snapshot, "values", {}) or {}
                if payload is not None:
                    interrupted = True
                    yield sse("interrupt", payload)
                else:
                    plan = final.get("trip_plan") or values.get("trip_plan")
                    validation = values.get("validation") or final.get("validation")
                    grounding = values.get("grounding") or final.get("grounding")
                    cancelled = bool(values.get("cancelled") or final.get("cancelled"))
                    rag_degraded = bool(
                        values.get("rag_degraded") or final.get("rag_degraded")
                    )
                    score = final.get("score")
                    span.set_attribute(
                        "run.score", float(score) if score is not None else 0.0
                    )
                    span.set_attribute("run.has_plan", bool(plan))
                    span.set_attribute("run.reply_length", len(final.get("reply") or ""))

                    warnings: list[str] = list((validation or {}).get("warnings") or [])
                    if grounding and grounding.get("ungrounded"):
                        warnings.append(
                            "以下景点未找到外部依据："
                            + "、".join(grounding.get("ungrounded") or [])
                        )
                    if grounding and not grounding.get("applicable", True):
                        warnings.append("本轮没有可用的外部证据，行程未做接地验证")
                    if rag_degraded:
                        warnings.append("攻略检索失败，本轮行程未使用 RAG 证据")
                    status = result_status(
                        plan, validation, grounding, cancelled=cancelled
                    )
                    if status == "degraded":
                        warnings.append("行程未通过全部确定性校验，仅供草稿参考")

                    yield sse("result", {
                        "status": status,
                        "trip_plan": plan,
                        "score": score,
                        "reply": final.get("reply") or values.get("reply"),
                        "options": final.get("options") or values.get("options"),
                        "trip_id": values.get("trip_id"),
                        "validation": validation,
                        "grounding": grounding,
                        "warnings": list(dict.fromkeys(warnings)),
                    })
                yield sse("done", {})
            except Exception as e:  # noqa: BLE001
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR))
                yield sse("error", {"code": 500, "msg": str(e)})
                yield sse("done", {})
            finally:
                if next_task is not None and not next_task.done():
                    next_task.cancel()
                    await asyncio.gather(next_task, return_exceptions=True)
                for child in node_spans.values():
                    child.set_attribute(
                        "node.status", "interrupted" if interrupted else "incomplete"
                    )
                    child.end()
                span.set_attribute("run.interrupted", interrupted)
    finally:
        release(lock)


async def _pg_status() -> str:
    """轻量探测 PG（2s 超时；连不上/池未打开都降级为 down，不阻塞 /health）。"""
    try:
        await asyncio.wait_for(fetch("SELECT 1"), timeout=2.0)
        return "ok"
    except Exception:  # noqa: BLE001
        return "down"


@app.get("/health")
async def health() -> dict:
    """健康检查：PG / Redis / LLM / MCP / Checkpoint 状态。"""
    return {
        "status": "ok",
        "pg": await _pg_status(),
        "redis": "ok" if redis_ready() else "down",
        "llm": "ok" if settings.deepseek_api_key else "unconfigured",
        "mcp": "ok" if amap_ready() else "unknown",
        "checkpoint": graph_module.checkpointer_kind(),
        "tracing": "on" if tracing_enabled() else "off",
        "auth": "on" if settings.auth_enabled else "off",
        "signed_session": bool(settings.require_signed_session),
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
            "auth_enabled": settings.auth_enabled,
            "require_signed_session": bool(settings.require_signed_session),
        },
    }


@app.post("/api/session")
async def create_session() -> dict:
    """签发会话 ID（REQUIRE_SIGNED_SESSION=true 时带 HMAC 签名）。"""
    session_id = new_session_id()
    if settings.require_signed_session:
        session_id = sign_session(session_id)
    return {"code": 0, "msg": "ok", "data": {"session_id": session_id}}


@app.post("/api/auth/login")
async def login(req: LoginRequest) -> dict:
    """用户名/密码换 JWT。"""
    if not settings.auth_enabled:
        raise HTTPException(400, "未启用鉴权")
    user = await authenticate_user(req.username, req.password)
    if user is None:
        raise HTTPException(401, "用户名或密码错误")
    token = create_access_token(str(user["id"]))
    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "access_token": token,
            "token_type": "bearer",
            "username": user["username"],
        },
    }


@app.get("/api/auth/me")
async def me(user_id: str | None = Depends(get_current_user)) -> dict:
    return {
        "code": 0,
        "msg": "ok",
        "data": {"user_id": user_id, "auth_enabled": settings.auth_enabled},
    }


@app.get("/api/prefs")
async def read_prefs(
    session_id: str = Query(min_length=1, max_length=128),
    user_id: str | None = Depends(get_current_user),
) -> dict:
    """读取当前会话偏好；Redis 不可用时返回空偏好（降级）。"""
    thread_id = thread_id_for(user_id, session_id)
    return {"code": 0, "msg": "ok", "data": {"prefs": await get_prefs(thread_id)}}


@app.post("/api/prefs")
async def update_prefs(
    req: PrefsRequest,
    user_id: str | None = Depends(get_current_user),
) -> dict:
    """增量更新偏好（只覆盖传入的非空字段）。"""
    thread_id = thread_id_for(user_id, req.session_id)
    ok = await save_prefs(
        thread_id,
        req.prefs.model_dump(exclude_none=True, exclude_unset=True),
    )
    if not ok:
        raise HTTPException(503, "偏好存储不可用")
    return {
        "code": 0,
        "msg": "ok",
        "data": {"prefs": await get_prefs(thread_id)},
    }


@app.get("/api/trips")
async def trips(
    session_id: str = Query(min_length=1, max_length=128),
    limit: int = Query(20, ge=1, le=50),
    user_id: str | None = Depends(get_current_user),
) -> dict:
    """历史行程列表（按用户 + 会话隔离）。"""
    thread_id = thread_id_for(user_id, session_id)
    rows = await list_trips(thread_id, limit)
    return {"code": 0, "msg": "ok", "data": {"trips": rows}}


@app.get("/api/trips/{trip_id}")
async def trip_detail(
    trip_id: int,
    session_id: str = Query(min_length=1, max_length=128),
    user_id: str | None = Depends(get_current_user),
) -> dict:
    """行程详情；不属于当前 session 的一律 404。"""
    thread_id = thread_id_for(user_id, session_id)
    row = await get_trip(trip_id, thread_id)
    if row is None:
        raise HTTPException(404, "行程不存在")
    return {"code": 0, "msg": "ok", "data": row}


@app.post("/api/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    user_id: str | None = Depends(get_current_user),
) -> StreamingResponse:
    """SSE 流：跑 LangGraph 图，推 progress / node / interrupt / result。"""
    thread_id = thread_id_for(user_id, req.session_id)
    state_in = {"user_input": req.message, "session_id": thread_id}
    config = {"configurable": {"thread_id": thread_id}}
    return StreamingResponse(
        stream_graph(state_in, config, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/resume")
async def resume(
    req: ResumeRequest,
    request: Request,
    user_id: str | None = Depends(get_current_user),
) -> StreamingResponse:
    """HITL 恢复：用确认/编辑后的任务清单继续跑同一 thread。"""
    thread_id = thread_id_for(user_id, req.session_id)
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph_module.graph.aget_state(config)
    if interrupt_payload(snapshot) is None:
        raise HTTPException(404, "没有待确认的任务")
    tasks = (
        None
        if req.tasks is None
        else sanitize_tasks(
            req.tasks,
            allowed_tools=set(all_tool_names()),
            max_tasks=settings.max_tasks,
        )
    )
    command = Command(resume={"tasks": tasks})
    return StreamingResponse(
        stream_graph(command, config, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# 生产/演示：FastAPI 直接托管前端构建产物（本地 Vite dev 不受影响）
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    _ASSETS = _FRONTEND_DIST / "assets"
    if _ASSETS.is_dir():
        app.mount("/assets", StaticFiles(directory=_ASSETS), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(_FRONTEND_DIST / "index.html")
