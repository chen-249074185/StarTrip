import asyncio
import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import settings

app = FastAPI(title="StarTrip Agent", version="0.1.0")


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
    """SSE 占位流：先推固定阶段事件，后续接入 LangGraph 图。"""

    async def event_stream():
        stages = [
            ("planning", "正在拆解任务..."),
            ("executing", "正在搜索景点（高德）..."),
            ("rag", "正在检索攻略知识库..."),
            ("reviewing", "正在审查行程..."),
        ]
        for stage, msg in stages:
            yield sse("progress", {"stage": stage, "msg": msg})
            await asyncio.sleep(0.3)
        yield sse("result", {"trip_plan": {}, "score": None})
        yield sse("done", {})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
