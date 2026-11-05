"""本地假 LLM 服务：用于容量压测，不消耗真实 DeepSeek 配额。

用法：
    .\\.venv\\Scripts\\python.exe -m uvicorn scripts.mock_llm_server:app --port 9999

然后另起一个应用实例（不要覆盖正在用的 8000）：
    $env:DEEPSEEK_BASE_URL="http://127.0.0.1:9999"
    $env:DEEPSEEK_API_KEY="mock"
    $env:HITL_ENABLED="false"
    $env:TRIP_PERSIST_ENABLED="false"
    .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001

压测：
    $env:LOAD_TEST_MESSAGE="你好"
    locust -f locustfile.py --headless -u 50 -r 5 -t 2m --host http://127.0.0.1:8001

这个服务只实现非流式 /chat/completions；它按 System Prompt 返回路由/规划/审查等
最小合法 JSON，用来测应用层容量，不代表真实模型质量。
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="StarTrip Mock LLM")


def _message_text(messages: list[dict[str, Any]]) -> tuple[str, str]:
    system = ""
    user = ""
    for message in messages:
        if message.get("role") == "system":
            system += str(message.get("content") or "")
        elif message.get("role") == "user":
            user += str(message.get("content") or "")
    return system, user


def _reply(system: str, user: str) -> str:
    if "意图路由器" in system:
        city = "上海" if "上海" in user else "北京" if "北京" in user else ""
        intent = "plan" if city else ("chat" if "你好" in user or "你是谁" in user else "recommend")
        return json.dumps({"intent": intent, "city": city}, ensure_ascii=False)

    if "任务拆解器" in system:
        return json.dumps(
            {
                "tasks": [
                    {"tool": "maps_text_search", "args": {"keywords": "必去景点", "city": "上海"}},
                    {"tool": "maps_weather", "args": {"city": "上海"}},
                ]
            },
            ensure_ascii=False,
        )

    if "旅行推荐官" in system:
        return json.dumps(
            {
                "reply": "现在是秋天，适合去这些城市走走。",
                "options": [
                    {"label": "上海", "value": "想去上海", "desc": "城市漫步与美食"},
                    {"label": "杭州", "value": "想去杭州", "desc": "西湖与秋色"},
                ],
            },
            ensure_ascii=False,
        )

    if "检索查询改写器" in system:
        return json.dumps(
            {"dense_queries": [user[:80] or "旅行攻略"], "keywords": ["景点", "美食"]},
            ensure_ascii=False,
        )

    if "行程审查官" in system:
        return json.dumps(
            {
                "trip_plan": {
                    "days": [
                        {
                            "date": "D1",
                            "spots": [
                                {"name": "外滩", "time": "09:00-11:00", "transport": "地铁", "budget": 0, "note": "免费"},
                                {"name": "豫园", "time": "13:00-15:00", "transport": "地铁", "budget": 40, "note": "园林"},
                            ],
                            "budget_total": 40,
                        },
                        {
                            "date": "D2",
                            "spots": [
                                {"name": "南京路", "time": "09:00-11:00", "transport": "步行", "budget": 0, "note": "购物"},
                            ],
                            "budget_total": 0,
                        },
                    ]
                },
                "score": 90,
                "dimensions": {"时间衔接": 90, "距离合理性": 90, "偏好匹配": 90, "预算控制": 90, "天气适配": 90},
                "reply": "已为你安排两日行程，综合评分 90 分。",
                "feedback": "",
            },
            ensure_ascii=False,
        )

    if "事实审查员" in system:
        return json.dumps(
            {
                "factual_consistency": 0.9,
                "grounded_rate": 0.9,
                "answer_coverage": 0.8,
                "issues": [],
            },
            ensure_ascii=False,
        )

    return "你好，我是 StarTrip 旅行助手。说说你想去哪、几天、预算？"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "mock-llm"}


@app.post("/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    body = await request.json()
    messages = body.get("messages") or []
    system, user = _message_text(messages)
    content = _reply(system, user)
    return JSONResponse(
        {
            "id": f"mock-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model") or "mock",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": max(1, len(user) // 2),
                "completion_tokens": max(1, len(content) // 2),
                "total_tokens": max(1, (len(user) + len(content)) // 2),
            },
        }
    )
