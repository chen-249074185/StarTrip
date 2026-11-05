"""Locust 压测脚本：对 /api/chat 做并发压测。

压测前请确保：
    HITL_ENABLED=false
    TRIP_PERSIST_ENABLED=false
    AUTH_ENABLED=false

用法：
    pip install locust
    locust -f locustfile.py --headless -u 10 -r 2 -t 2m \
      --host http://127.0.0.1:8000 --csv reports/load10

说明：
- 每个虚拟用户使用独立 session_id，避免 Checkpoint 互相覆盖；
- 默认消息是完整规划请求，适合真实链路压测（5–10 并发）；
- 容量压测建议配合 scripts/mock_llm_server.py，并把 LOAD_TEST_MESSAGE 设为“你好”，
  只压 FastAPI/SSE/Checkpoint/Redis，不消耗真实 LLM 与高德配额。
"""

from __future__ import annotations

import os
import uuid

from locust import HttpUser, between, task


class AgentUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.session_id = f"load-{uuid.uuid4().hex[:8]}"
        self.message = os.getenv("LOAD_TEST_MESSAGE", "上海两日游，预算2000")

    @task
    def chat(self) -> None:
        self.client.post(
            "/api/chat",
            json={"session_id": self.session_id, "message": self.message},
            timeout=60,
        )
