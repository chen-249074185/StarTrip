# StarTrip Agent

多 Agent 旅行规划系统（Python / LangGraph / FastAPI）。

用户以自然语言描述出行需求（目的地、天数、预算、偏好），系统通过 LangGraph 图式编排多个 Agent 节点（规划 / 执行 / RAG / 审查），调度高德与天气服务完成数据采集，结合 RAG 知识库增强推荐，最终输出带评分的完整行程，并在 Web 端以行程卡片 + 地图可视化呈现。

## 技术栈

| 层 | 选型 |
|---|---|
| Web 框架 | FastAPI（SSE 流式） |
| Agent 编排 | LangGraph（状态图 + 条件回环） |
| LLM | DeepSeek ds-4.1-flash |
| Embedding | text-embedding-v3（DashScope，1024 维） |
| 工具 | 高德 MCP（POI / 路线 / 周边）+ 天气服务 |
| 向量库 | PostgreSQL + pgvector |
| 缓存 / 记忆 | Redis |
| 前端 | Vue 3 + Vite + 高德 JS API |
| 可观测 | OpenTelemetry + Jaeger |
| 评测 | 独立 LLM-as-judge + golden set |
| 测试 | pytest + httpx |
| 部署 | docker-compose（PG + Redis + Jaeger + app） |

## 快速开始

```powershell
# 1. 依赖
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. 配置密钥
Copy-Item .env.example .env   # 然后填入真实 key

# 3. 起数据库与缓存
docker compose up -d

# 4. 启动服务
uvicorn app.main:app --reload
```

## Docker 部署

```powershell
# 1. 配置密钥（compose 会自动读取 .env）
Copy-Item .env.example .env   # 填 DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / AMAP_KEY 等

# 2. 起全部服务（PostgreSQL + Redis + Jaeger + app）
docker compose up -d --build

# 3. 健康检查
Invoke-RestMethod http://localhost:8000/health
```

- 首次部署需构建知识库（容器内执行）：
  ```powershell
  docker compose exec -T app python -m scripts.build_kb
  ```
- 前端仍需单独启动：`cd frontend; npm run dev`（或 `npm run build` 后托管 `dist/`）
- HITL 默认开启；全自动规划可设 `HITL_ENABLED=false`
- 可观测：`OTEL_ENABLED=true`，Jaeger UI `http://localhost:16686`
- 离线评测：`docker compose exec -T app python -m scripts.run_eval --limit 3`

## 目录结构

```
StarTrip/
├── app/                # 应用代码
│   ├── main.py         # FastAPI 入口 + SSE
│   ├── graph.py        # LangGraph 图定义
│   └── nodes/          # 规划/执行/RAG/审查节点
├── scripts/            # 离线脚本（知识库构建）
├── tests/              # pytest
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## 状态

M0~M8 已完成：多 Agent 编排、工具、RAG、审查回环、Vue 前端、可靠性四件套、Checkpoint/多轮记忆、HITL、OTel 可观测、LLM-as-judge 离线评测。持续补测试与部署细节。
