# StarTrip Agent

多 Agent 旅行规划系统（Python / LangGraph / FastAPI）。

用户以自然语言描述出行需求（目的地、天数、预算、偏好），系统通过 LangGraph 图式编排多个 Agent 节点（规划 / 执行 / RAG / 审查），调度高德与天气服务完成数据采集，结合 RAG 知识库增强推荐，最终输出带评分的完整行程，并在 Web 端以行程卡片 + 地图可视化呈现。

## 技术栈

| 层 | 选型 |
|---|---|
| Web 框架 | FastAPI（SSE 流式） |
| Agent 编排 | LangGraph（状态图 + 条件回环） |
| LLM / Embedding | 通义千问 qwen-plus / text-embedding-v3（DashScope） |
| 工具 | 高德（POI / 路线 / 周边）+ 天气服务 |
| 向量库 | PostgreSQL + pgvector |
| 缓存 / 记忆 | Redis |
| 前端 | Vue 3 + Vite + 高德 JS API |
| 测试 | pytest + httpx |
| 部署 | docker-compose（PG + Redis） |

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

开发中。
