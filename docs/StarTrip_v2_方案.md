# StarTrip Agent · 多 Agent 旅行规划系统 —— 详细技术方案（v2）

> 版本：v2 定稿（LangGraph 技术栈）
> 状态：开发计划 4 天 · 简历条目已同步
> 面试定位：Python / AI Agent 岗位的核心展示项目

---

## 1. 项目概述

### 1.1 定位
基于 Python 的**多 Agent 旅行规划系统**：用户以自然语言描述出行需求（目的地、天数、预算、偏好），系统通过 LangGraph 图式编排多个 Agent 节点（规划/执行/审查），调度高德 MCP 与天气服务完成数据采集，结合 RAG 知识库增强推荐，最终输出带评分的完整行程方案，并在 Web 端以行程卡片 + 高德地图可视化呈现。

### 1.2 核心卖点（面试关键词）
- 多 Agent 图式编排（LangGraph 状态图 + 条件回环）
- MCP 工具编排（高德 MCP：POI 检索 / 路线规划 / 周边查询）
- asyncio 并发工具调用（多工具并行，响应链路优化）
- RAG 检索增强（PostgreSQL + pgvector 向量检索）
- 行程质量多目标评测（时间衔接 / 距离 / 偏好匹配）
- 多轮对话记忆（Redis 偏好跨轮复用）
- Web 端实时交互（FastAPI SSE 流式输出 + Vue 3 前端 + 高德 JS API 地图可视化）

### 1.3 项目定位
独立设计并实现的多 Agent 应用，采用 Python 现代技术栈（LangGraph + FastAPI + pgvector），覆盖"编排 + 工具 + RAG + 评测"完整链路。

---

## 2. 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| Web 框架 | FastAPI | Python 异步首选、原生 SSE 支持、pydantic 校验，2026 Agent 岗标配 |
| Agent 编排 | LangGraph | LangChain 官方图式编排框架，状态管理 + 条件边 + 回环，面试热点 |
| LLM | DashScope（通义千问） | 用户已有 API、Function Calling 成熟 |
| 工具 | 高德 MCP（POI/路线/周边）+ 天气服务 | MCP 协议 + 真实业务工具编排 |
| 向量库 | PostgreSQL + pgvector | 生产级"一库两用"（业务数据 + 向量），比 Qdrant 更贴合后端岗面试 |
| 缓存/记忆 | Redis | 偏好缓存 + TTL，复用用户既有 Redis 经验 |
| 前端 | Vue 3 + Vite + 高德 JS API | 组件化 + 响应式，行程卡片/流式对话易维护；工程规范、面试加分 |
| 测试 | pytest + httpx | 覆盖图全链路与 API |
| 部署 | docker-compose（PG + Redis） | 与用户既有 Docker 经验一致 |

### 2.1 模型选型（本项目实际使用）

| 用途 | 模型 | 说明 |
|---|---|---|
| LLM（规划/审查节点） | 通义千问 qwen-plus（DashScope） | 需求→任务拆解（Function Calling 输出 JSON 工具清单）；行程生成 + 5 维评分；回环时携带 feedback 修正 |
| Embedding（RAG） | text-embedding-v3（DashScope） | 攻略文档/查询向量化（1024 维），供 pgvector 余弦检索 |
| 执行节点 | 非 LLM（纯工具调度） | asyncio + MCP 客户端直接调用高德/天气 API，无需 LLM 推理 |

### 2.2 多 Agent 澄清（面试必答）

**多 Agent 不是"多个大模型"，而是"多个角色节点"**——由同一个 LLM（qwen-plus）通过不同 System Prompt 扮演不同角色驱动：

- 规划 Agent：qwen-plus + "你是旅行规划师"提示词 → 输出任务清单
- 执行 Agent：不调用 LLM，纯工具调度（asyncio 并发调用高德 MCP + 天气）
- 审查 Agent：qwen-plus + "你是行程审查官"提示词 → 生成行程 + 5 维打分

**可选进阶（面试可提）**：规划/审查分别用 qwen-max（更强推理）/ qwen-plus（成本低）做多模型分工。本项目默认"单模型多角色"，面试讲取舍：多角色提示词分工 = 成本低、逻辑一致；多模型分工 = 质量高、成本高——中小项目选前者，讲得出来就是加分。

---

## 3. 系统架构

```
用户
  │
  ▼
┌─────────────────────────────────────────────┐
│ Web 前端（Vue 3 + Vite + 高德 JS API）          │
│  对话页（聊天 + 流式输出）                      │
│  行程页（Day1/Day2 时间线卡片）                │
│  地图页（景点标记 + 路线连线）                  │
└──────────────┬──────────────────────────────┘
               │ REST / SSE
               ▼
┌─────────────────────────────────────────────┐
│ FastAPI 应用层                               │
│  main.py：路由 + SSE 流式                    │
│  graph.py：LangGraph 图定义                  │
└──────────────┬──────────────────────────────┘
               │ 状态流转
               ▼
┌─────────────────────────────────────────────┐
│ LangGraph 图（4 节点 + 条件回环）              │
│  规划节点 → 执行节点 → RAG 节点 → 审查节点     │
│        ↑___________ 审查不达标，条件边回环 ____│
└──────┬──────────┬──────────┬────────┬────────┘
       │          │          │        │
       ▼          ▼          ▼        ▼
  高德 MCP    天气服务   PostgreSQL   Redis
  (POI/路线)  (天气)   (pgvector)  (偏好)
```

---

## 4. 核心流程

### 4.1 用户视角流程
1. 用户在对话页输入："帮我规划上海两日游，预算 1000，不爱走路"
2. 前端 SSE 实时展示规划过程：
   - 规划中 → 正在搜索景点（高德）→ 正在规划路线 → 正在检索攻略知识库 → 正在审查行程
3. 输出行程卡片（Day1/Day2：景点 + 交通 + 时间 + 预算 + 评分）
4. 地图页同步展示：景点标记 + 路线连线
5. 用户追加："第二天不要博物馆" → 系统结合偏好重新规划
6. 偏好（不爱走路 / 不要博物馆）存入 Redis，下次对话自动复用

### 4.2 系统时序（一次完整规划）
```
User → FastAPI(/api/chat SSE) → LangGraph 图
  → 规划节点：LLM 将需求拆成任务列表
      [{tool: amap_poi, arg: {city, keyword}}, {tool: amap_route, ...}, {tool: weather, ...}]
  → 执行节点：asyncio.gather 并发执行工具，收集结果
      amap_poi → 候选景点列表（含评分/门票/位置）
      weather → 每日天气
  → RAG 节点：候选景点名 → pgvector 检索攻略知识库 → 补充游玩建议/避坑信息
  → 审查节点：LLM 综合信息生成行程（含时间/交通/预算），按 5 维打分
  → 打分 < 阈值：条件边回环 → 规划节点重新调整 → 再次执行
  → 打分达标：行程 JSON 写入 PG(trips)，SSE 推回前端
```

---

## 5. LangGraph 图设计（核心）

### 5.1 状态（State）
```python
class TripState(TypedDict):
    user_input: str              # 原始需求
    tasks: list[dict]            # 规划节点输出的任务列表
    tool_results: dict           # 执行节点收集的工具结果
    rag_hints: list[str]         # RAG 检索补充
    trip_plan: dict | None       # 行程方案
    score: float | None          # 审查评分
    feedback: str | None         # 审查不达标原因（回环输入）
    retry_count: int             # 回环次数上限（防死循环）
```

### 5.2 节点
| 节点 | 职责 | 输入 → 输出 | 关键实现 |
|---|---|---|---|
| 规划节点 planner | 需求→任务拆解 | user_input+feedback → tasks | LLM 结构化输出工具调用清单；重试时携带 feedback 修正 |
| 执行节点 executor | 工具调度 | tasks → tool_results | asyncio.gather 并发；MCP 客户端调用；超时/降级 |
| RAG 节点 retriever | 知识增强 | tool_results → rag_hints | 景点名提取 → embedding → pgvector topK 检索 → 注入提示词 |
| 审查节点 reviewer | 行程生成+评分 | 汇总 → trip_plan+score | LLM 生成行程 + 结构化评分；输出不达标原因 |

### 5.3 边与回环
```
START → planner → executor → retriever → reviewer → END
                              ↑___________│
                     score < 阈值 且 retry < 3 → 回 planner（携带 feedback）
                     score ≥ 阈值 或 retry ≥ 3 → END（输出当前最优）
```
- 条件边：reviewer 后判断 score
- 防死循环：retry_count 上限 3 次（步数上限思想，避免无效重试烧 Token）

---

## 6. 模块详细设计

### 6.1 规划节点（planner.py）
- 提示词要求 LLM 输出 JSON 任务列表，字段：
  ```json
  [{"tool": "amap_poi", "args": {"city": "上海", "keyword": "必去景点"}},
   {"tool": "amap_route", "args": {"origin": "外滩", "dest": "豫园", "city": "上海"}},
   {"tool": "weather", "args": {"city": "上海", "days": 2}}]
  ```
- 回环修正：第二次进入时输入中加入 `feedback: "上次行程评价：距离衔接过紧，请减少每日景点数量"`

### 6.2 执行节点（executor.py）
- asyncio 并发：
  ```python
  async def executor(state):
      tasks = state["tasks"]
      results = await asyncio.gather(*[call_tool(t) for t in tasks])
      return {"tool_results": dict(zip([t["tool"] for t in tasks], results))}
  ```
- MCP 客户端（amap_mcp.py）：通过 MCP SDK 或 HTTP 调用高德开放平台：
  - POI 搜索：/v3/place/text（关键词 → 景点候选：名称/坐标/评分/门票）
  - 路线规划：/v3/direction/driving（或步行/公交，按偏好选）
  - 周边查询：/v3/place/around
- 天气工具（weather.py）：城市天气 API，返回逐日天气，供行程适配（雨天调室内景点）

### 6.3 RAG 节点（rag.py）—— 查询改写 + 混合检索（两层）

**动机**：用户 query 口语化、候选景点是专有名词，单路向量检索两头都不讨好——语义漂、精确词丢。故采用两层：先用 LLM 把 query 改写成"检索友好"的多路查询，再走**混合检索**（dense 余弦 + sparse 关键词，RRF 融合）。不引入 cross-encoder rerank（库小、收益低于延迟成本，见 2.2 取舍话术）。

```
tool_results（候选景点/城市/需求）
   │
   ① Query Rewrite（qwen-plus）→ {dense_queries:[...], keywords:[...]}
   │
   ② Hybrid Retrieval ─┬─ Dense：embedding → pgvector 余弦 (<=>) topN
   │                   └─ Sparse：关键词命中 topN
   │                   └─ RRF 融合
   ▼
rag_hints (topK) → 注入审查节点提示词
```

#### 6.3.1 第一层：查询改写

```python
# rag.py —— 查询改写层：口语 query → 检索友好多路查询
REWRITE_PROMPT = """你是检索查询改写器。根据用户需求与候选景点，输出 JSON：
{"dense_queries": ["...", "..."],   # 2~3 条，面向向量检索，补玩法/同义词/避坑
 "keywords": ["...", "..."]}         # 3~6 个，面向关键词精确匹配的地名/设施名
只输出 JSON，不要解释。"""

async def rewrite(user_input: str, spots: list[str], city: str) -> dict:
    msg = f"用户需求:{user_input}\n城市:{city}\n候选景点:{spots}"
    try:
        raw = await llm.chat(REWRITE_PROMPT, msg, response_format="json_object")
        data = json.loads(raw)
        dense = data.get("dense_queries") or [f"{city} {user_input}"]
        kws = data.get("keywords") or [s for s in spots[:5]]
        return {"dense_queries": dense[:3], "keywords": kws[:6]}
    except Exception:
        # LLM 失败/非法 JSON：降级为原始 query，保证链路不中断
        return {"dense_queries": [f"{city} {user_input}"], "keywords": spots[:5]}
```

#### 6.3.2 第二层：混合检索

**Dense（语义·余弦）**——在 embedding 空间找"语义相近区域"：

```python
# 余弦距离操作符 <=>（1 - cos_sim），越小越近；$1 = text-embedding-v3 向量(1024)
DENSE_SQL = """
SELECT id, content,
       1 - (embedding <=> $1::vector) AS sim
FROM docs
ORDER BY embedding <=> $1::vector
LIMIT $2;
"""

async def dense_search(queries: list[str], topn: int = 20) -> list[int]:
    ids = []
    for q in queries:                          # 多路 query 各召回，去重合并
        emb = await embed(q)                   # text-embedding-v3 → 1024 维
        rows = await db.fetch(DENSE_SQL, emb, topn)
        ids.extend(r["id"] for r in rows)
    return list(dict.fromkeys(ids))            # 保序去重
```

**Sparse（词法·关键词）**——补向量不敏感的精确词（"豫园""地铁2号线"）：

```python
# pgvector 官方镜像默认无 zhparser，用命中级数法（零依赖、够用）；
# 升级可换 zhparser/pg_jieba + tsvector
SPARSE_SQL = """
SELECT id, content,
       (CASE WHEN content ILIKE $1 THEN 1 ELSE 0 END
      + CASE WHEN content ILIKE $2 THEN 1 ELSE 0 END
      + CASE WHEN content ILIKE $3 THEN 1 ELSE 0 END) AS hits
FROM docs
WHERE content ILIKE $1 OR content ILIKE $2 OR content ILIKE $3
ORDER BY hits DESC
LIMIT $4;
"""

async def sparse_search(keywords: list[str], topn: int = 20) -> list[int]:
    k = (keywords + ["", "", ""])[:3]
    like = [f"%{w}%" for w in k]
    rows = await db.fetch(SPARSE_SQL, like[0], like[1], like[2], topn)
    return [r["id"] for r in rows]
```

**融合：RRF（Reciprocal Rank Fusion）**——无需归一化、无需调权重：

```python
def rrf(dense_ids: list[int], sparse_ids: list[int], k: int = 60, topk: int = 5) -> list[int]:
    score: dict[int, float] = {}
    for ids in (dense_ids, sparse_ids):
        for rank, doc_id in enumerate(ids):
            score[doc_id] = score.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(score, key=score.get, reverse=True)[:topk]
```

#### 6.3.3 节点装配（LangGraph retriever）

```python
async def retriever_node(state: TripState) -> dict:
    user_input = state["user_input"]
    results = state["tool_results"]
    city = results.get("city", "")
    spots = extract_spot_names(results.get("amap_poi", []))   # 候选景点名

    # ① 改写
    rw = await rewrite(user_input, spots, city)

    # ② 混合检索并发（复用项目"asyncio 并发"卖点）
    dense_ids, sparse_ids = await asyncio.gather(
        dense_search(rw["dense_queries"]),
        sparse_search(rw["keywords"]),
    )

    # ③ 融合 → topK 原文
    fused = rrf(dense_ids, sparse_ids, topk=5)
    hints = await db.fetch_contents(fused)          # 取 content 原文
    return {"rag_hints": hints}
```

#### 6.3.4 知识库构建（离线脚本 · 微调）

保留原方案（512 字符 / 50 重叠 / text-embedding-v3 1024 维）。`content ILIKE` 可直接支撑 sparse，无需额外列：

```sql
CREATE TABLE docs (
  id         BIGSERIAL PRIMARY KEY,
  title      TEXT,
  content    TEXT,
  embedding  VECTOR(1024)
);
CREATE INDEX ON docs USING hnsw (embedding vector_cosine_ops);
```

#### 6.3.5 测试用例（test_rag.py，配合第 10 节）

| 用例 | 覆盖 | 断言 |
|---|---|---|
| test_rewrite_json_format | 改写层结构 | mock LLM 返回合法 JSON → 字段/条数符合约定（dense≤3, keywords≤6） |
| test_rewrite_fallback | 改写降级 | LLM 抛异常/返回非法 JSON → 回退原始 query，不抛错 |
| test_dense_search_cosine | 向量召回 | mock embed + mock DB → 走余弦 SQL、多 query 去重合并 |
| test_sparse_search_hits | 关键词召回 | 命中数降序、空关键词容错 |
| test_rrf_fusion_order | 融合排序 | 给定固定 dense/sparse 序列 → RRF 输出顺序正确 |
| test_retriever_node_e2e | 节点全链路 | 全 mock → `state["rag_hints"]` 非空且长度 ≤ topK |

### 6.4 审查节点（reviewer.py）
- LLM 生成行程 JSON：
  ```json
  {"days": [{"date": "D1", "spots": [
      {"name": "外滩", "time": "09:00-11:00", "transport": "地铁2号线",
       "budget": 0, "note": "避开人流建议：早上去"}],
    "budget_total": 320}]}
  ```
- 评分维度（0-100）：
  - 时间衔接（景点间是否顺路、是否过紧）
  - 距离合理性（单日通勤总时长）
  - 偏好匹配（是否满足"不爱走路/不要博物馆"等约束）
  - 预算控制
  - 天气适配
- 不达标 → 返回 feedback（哪条失分）→ 回环

### 6.5 记忆模块（memory.py）
- Redis 结构：`prefs:{session_id}` → hash（口味/交通偏好/已排除景点）
- TTL：30 分钟活跃会话 / 7 天长期
- 规划节点提示词注入历史偏好；用户否定某景点时自动记录"排除项"

---

## 7. 数据模型（PostgreSQL）

```sql
-- 行程表
CREATE TABLE trips (
  id          BIGSERIAL PRIMARY KEY,
  session_id  TEXT NOT NULL,
  title       TEXT,
  plan_json   JSONB NOT NULL,          -- 完整行程
  score       NUMERIC(5,2),
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- 偏好表
CREATE TABLE prefs (
  session_id  TEXT PRIMARY KEY,
  prefs_json  JSONB NOT NULL,
  updated_at  TIMESTAMPTZ DEFAULT now()
);

-- 知识库（pgvector）
CREATE TABLE docs (
  id         BIGSERIAL PRIMARY KEY,
  title      TEXT,
  content    TEXT,
  embedding  VECTOR(1024)
);
CREATE INDEX ON docs USING hnsw (embedding vector_cosine_ops);
```

---

## 8. API 设计

### 8.1 POST /api/chat（SSE 流式）
请求：
```json
{"session_id": "s1", "message": "帮我规划上海两日游，预算1000，不爱走路"}
```
SSE 事件序列：
```
event: progress   data: {"stage": "planning", "msg": "正在拆解任务..."}
event: progress   data: {"stage": "executing", "msg": "正在搜索景点（高德）..."}
event: progress   data: {"stage": "rag", "msg": "正在检索攻略知识库..."}
event: result     data: {行程 JSON + score}
event: done
```

### 8.2 其他接口
| 接口 | 说明 |
|---|---|
| GET /api/trips?session_id= | 历史行程列表 |
| GET /api/trips/{id} | 行程详情（前端回看/地图加载） |
| GET /api/prefs?session_id= | 偏好读取 |
| POST /api/prefs | 偏好更新（前端可手动调整） |

---

## 9. Web 前端设计（Vue 3 + Vite）

### 9.1 工程结构
```
frontend/
├── index.html
├── vite.config.js          # /api 代理到 FastAPI
├── package.json
└── src/
    ├── main.js
    ├── App.vue
    ├── api/                # fetch/axios 封装（带 JWT）
    ├── composables/
    │   ├── useSSE.js       # fetch + ReadableStream 解析 SSE
    │   └── useAmap.js      # 动态加载高德 JS API
    └── components/
        ├── ChatPanel.vue    # 对话页
        ├── TripDayCard.vue  # Day 分组行程卡片
        └── TripMap.vue      # 地图页
```
- 技术：Vue 3 `<script setup>` + Vite；状态 `ref/reactive`（可选 pinia）
- 开发：`vite dev` 起 5173，`vite.config` 里 `proxy: { '/api': 'http://localhost:8000' }`；生产 `vite build` → `dist/` 交 FastAPI 静态托管

### 9.2 对话页（ChatPanel.vue）
- 聊天界面：消息气泡 + 输入框
- SSE 流式渲染：`useSSE` composable（`fetch` + `ReadableStream` 手动解析；`EventSource` 不能带 header，带 JWT 用 fetch）
- 规划阶段提示（planning / executing / rag）实时 push 进消息列表（打字机效果）
- 行程结果以 `TripDayCard` 组件渲染（Day 分组：景点 + 交通 + 时间 + 预算 + 评分）

### 9.3 地图页（TripMap.vue）
- `useAmap` 动态注入 `<script src="https://webapi.amap.com/maps?v=2.0&key=...">`，key/securityCode 走后端接口下发（不硬编码）
- `onMounted` 初始化 map，`onUnmounted` 调 `map.destroy()` 防内存泄漏
- 景点标记 `new AMap.Marker({position:[lng,lat]})` + InfoWindow；路线连线 `new AMap.Polyline({path})`
- 点击景点 → 弹窗显示攻略建议（来自 RAG 检索结果）

---

## 10. 测试方案（pytest）

| 用例组 | 覆盖 | 数量 |
|---|---|---|
| test_graph.py | 图完整链路（mock 工具）：输入→行程输出 | 5 |
| test_planner.py | 任务拆解 JSON 格式校验、回环修正 | 3 |
| test_executor.py | asyncio 并发调用、工具超时降级 | 3 |
| test_rag.py | 查询改写结构/降级、余弦召回、关键词召回、RRF 融合、节点全链路 | 6 |
| test_reviewer.py | 评分逻辑、不达标回环触发 | 3 |
| test_api.py | /api/chat SSE 事件序列、/api/trips CRUD | 5 |
| 合计 | | ~25 |

- mock 策略：工具/LLM 全部 mock（不烧 Token、可回归）
- 核心逻辑全部可回归验证（工具/LLM mock，不烧 Token）

---

## 11. 部署（docker-compose.yml）

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment: [POSTGRES_DB=startrip, POSTGRES_USER=user, POSTGRES_PASSWORD=pass]
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
  redis:
    image: redis:7
    ports: ["6379:6379"]
volumes: { pgdata: {} }
```



## 12. 开发计划（4 天）

| 天 | 任务 | 验收标准 |
|---|---|---|
| D1 | LangGraph 官方 tutorial（半天）；图骨架（4 节点占位）；FastAPI 入口 + SSE | /api/chat 能返回空流程事件 |
| D2 | 高德 MCP 客户端（POI/路线/周边）；天气工具；asyncio 并发；docker-compose 起 PG+Redis | 工具调用返回真实数据 |
| D3 | pgvector 建表 + 知识库构建脚本；RAG 检索；Redis 记忆；Vue 前端工程（Vite）+ 对话页流式展示 | 端到端能规划出带 RAG 提示的行程 |
| D4 | 审查评分 + 条件回环；行程卡片 + 地图组件（Vue）；pytest ~25 用例；简历定稿 | 全链路可演示 + 测试全绿 |

---



