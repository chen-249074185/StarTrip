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

## 一键启动（Windows）

1. 先打开 Docker Desktop（等它显示 Running）
2. 双击项目根目录的 **`start.bat`**
3. 浏览器打开 **http://localhost:8000**

停止服务：双击 `stop.bat`（会停掉 app + PostgreSQL + Redis + Jaeger）。

## 快速开始（本地开发）

```powershell
# 1. 依赖
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. 配置密钥
Copy-Item .env.example .env   # 然后填入真实 key

# 3. 起数据库与缓存
docker compose up -d

# 4. 启动服务（不要直接运行 app/main.py）
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

前端开发模式：另开终端 `cd frontend; npm run dev`，访问 `http://localhost:5173`。

## Docker 部署

```powershell
# 1. 配置密钥（compose 会自动读取 .env）
Copy-Item .env.example .env   # 填 DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / AMAP_KEY 等

# 2. 起全部服务（PostgreSQL + Redis + Jaeger + app）
docker compose up -d --build

# 3. 打开应用（前端已内置）
start http://localhost:8000
```

- Docker 镜像会多阶段构建前端，FastAPI 直接托管 `frontend/dist`，**不需要再单独起前端**
- 首次部署需构建知识库（容器内执行）：
  ```powershell
  docker compose exec -T app python -m scripts.build_kb
  ```
- 本地前端开发仍可用 `cd frontend; npm run dev`（5173，代理到 8000）
- HITL 默认开启；全自动规划可设 `HITL_ENABLED=false`
- 可观测：`OTEL_ENABLED=true`，Jaeger UI `http://localhost:16686`
- 离线评测：`docker compose exec -T app python -m scripts.run_eval --limit 3`

## 鉴权（可选）

默认 `AUTH_ENABLED=false`，不改变原有 demo 行为。开启：

```powershell
# .env
AUTH_ENABLED=true
JWT_SECRET=<随机长字符串>

# 创建/重置用户（本地）
python -m scripts.create_user admin

# Docker
docker compose exec -T app python -m scripts.create_user admin
```

开启后前端会显示登录页；`/api/chat`、`/api/resume` 需要 `Authorization: Bearer <JWT>`，Checkpoint 按 `user_id:session_id` 隔离。token 默认 120 分钟过期。

## 偏好（Redis）

```powershell
POST /api/prefs   {"session_id":"s1","prefs":{"budget":1000,"must_avoid":["博物馆"]}}
GET  /api/prefs?session_id=s1
```

偏好按 `prefs:{thread_id}` 存 Redis，默认 7 天 TTL；planner/reviewer/recommend 会自动注入。Redis 不可用时 GET 返回空、POST 返回 503，不阻断主流程。

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

M0~M8 已完成：多 Agent 编排、工具、RAG、审查回环、Vue 前端、可靠性四件套、Checkpoint/多轮记忆、HITL、OTel 可观测、LLM-as-judge 离线评测、Docker 部署；JWT 鉴权、行程落库（`/api/trips`）与 Redis 偏好（`/api/prefs`）已实现。
