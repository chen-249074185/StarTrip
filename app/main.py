import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import settings
from app.graph import graph
from app.tools import close_amap


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_amap()   # 应用关闭时释放 MCP 会话


app = FastAPI(title="StarTrip Agent", version="0.1.0", lifespan=lifespan)

# 节点名 → SSE 阶段提示
STAGE_MAP = {
    "planner": ("planning", "正在拆解任务..."),
    "executor": ("executing", "正在搜索景点（高德）..."),
    "retriever": ("rag", "正在检索攻略知识库..."),
    "reviewer": ("reviewing", "正在审查行程..."),
}


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
                if name not in STAGE_MAP:
                    continue
                if ev["event"] == "on_chain_start":
                    stage, msg = STAGE_MAP[name]
                    yield sse("progress", {"stage": stage, "msg": msg})
                elif ev["event"] == "on_chain_end":
                    out = ev["data"].get("output")
                    if isinstance(out, dict):
                        final.update(out)
            yield sse("result", {"trip_plan": final.get("trip_plan"), "score": final.get("score")})
            yield sse("done", {})
        except Exception as e:  # noqa: BLE001
            yield sse("error", {"code": 500, "msg": str(e)})
            yield sse("done", {})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
