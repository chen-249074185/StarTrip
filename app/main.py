
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import settings
from app.db.pg import close_pool, init_schema, open_pool
from app.graph import graph
from app.tools import close_amap


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        open_pool()
        await init_schema()
    except Exception as e:  # noqa: BLE001
        print(f"[startup] PG 未就绪，跳过初始化: {e}")
    yield
    await close_amap()   # 释放 MCP 会话
    close_pool()


app = FastAPI(title="StarTrip Agent", version="0.1.0", lifespan=lifespan)

# 节点名 → (SSE 阶段, 开始提示)
NODE_STAGE = {
    "planner": ("planning", "正在拆解任务..."),
    "executor": ("executing", "正在搜索景点（高德）..."),
    "retriever": ("rag", "正在检索攻略知识库..."),
    "reviewer": ("reviewing", "正在审查行程..."),
}


def node_summary(name: str, out: dict) -> dict:
    """把节点产出压成一句可展示的摘要，让前端看得出"这一步成功没有"。"""
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


def sse(event: str, data: dict) -> str:
    """格式化为 SSE 事件块。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/health")
async def health() -> dict:
    """健康检查：后续接入 PG / Redis / LLM / MCP 的真实探测。"""
    return {
        "status": "ok",
        "pg": "unknown",
        "redis": "unknown",
        "llm": "ok" if settings.deepseek_api_key else "unconfigured",
        "mcp": "unknown",
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
    """SSE 流：跑 LangGraph 图，把节点事件转成 progress，最后推 result。"""

    async def event_stream():
        state_in = {"user_input": req.message, "session_id": req.session_id}
        config = {"configurable": {"thread_id": req.session_id}}
        final: dict = {}
        try:
            async for ev in graph.astream_events(state_in, config, version="v2"):
                name = ev.get("name")
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
            yield sse("result", {"trip_plan": final.get("trip_plan"), "score": final.get("score")})
            yield sse("done", {})
        except Exception as e:  # noqa: BLE001
            yield sse("error", {"code": 500, "msg": str(e)})
            yield sse("done", {})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
