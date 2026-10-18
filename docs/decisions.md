# 设计决策记录（ADR）

> 记录"为什么这么选"，便于回看取舍理由。每条：背景 / 决定 / 放弃 / 影响。
> 新增：复制文末模板，编号递增。

## D1 · Web 框架：FastAPI
- 日期：2026-10-16
- 背景：需要异步、原生 SSE 流式、请求体类型校验
- 决定：FastAPI
- 放弃：Flask（同步为主，SSE 需额外依赖）、Django（偏重，本项目无需 ORM/后台）
- 影响：原生 StreamingResponse、pydantic 校验、异步生态契合 Agent 编排

## D2 · Agent 编排：LangGraph
- 日期：2026-10-16
- 背景：多节点（规划/执行/RAG/审查）+ 条件回环 + 共享状态
- 决定：LangGraph 状态图（StateGraph + 条件边）
- 放弃：手写 while 循环（无状态图、难扩展难测试）、CrewAI/AutoGen（偏对话式多智能体，图式流程控制弱）
- 影响：状态管理 + 条件边 + 回环天然支持"不达标重规划"

## D3 · 前端：Vue 3 + Vite
- 日期：2026-10-16
- 背景：行程卡片（Day 分组）+ SSE 流式对话 + 高德地图
- 决定：Vue 3（`<script setup>`）+ Vite
- 放弃：原生 HTML/JS（免构建，但数据驱动靠手写 DOM，维护差）
- 影响：引入 Node 构建链，约 +0.5~1 天；开发用 Vite proxy 转发 /api

## D4 · RAG 检索：查询改写 + 混合检索（不引入 rerank）
- 日期：2026-10-16
- 背景：query 口语化、候选景点是专有名词，单路向量检索语义漂、精确词丢
- 决定：两层——LLM 查询改写（dense_queries + keywords）→ 混合检索（dense 余弦 + sparse 关键词，RRF 融合）
- 放弃：cross-encoder rerank（库小、收益低于延迟/成本，文档量上去后再评估）
- 影响：召回质量提升，零额外模型依赖

## D5 · 向量库：PostgreSQL + pgvector
- 日期：2026-10-16
- 背景：业务数据 + 向量都要存
- 决定：单库 pgvector（余弦 HNSW 索引）
- 放弃：Qdrant（独立服务，一库两用收益低）
- 影响：一库两用，减少运维；中文 sparse 用 `ILIKE` 命中（后续可升级 zhparser）

## D6 · LLM：DeepSeek ds-4.1-flash（Embedding 仍用 DashScope）
- 日期：2026-10-16
- 背景：需要便宜且支持 Function Calling 的对话模型；RAG 向量另需 embedding
- 决定：LLM 用 DeepSeek `ds-4.1-flash`；Embedding 保持 DashScope `text-embedding-v3`（1024 维）
- 放弃：全用 DashScope qwen-plus（成本更高）、LLM 与 Embedding 全用 DeepSeek（无合适 embedding）
- 影响：LLM 与 Embedding 解耦、各自选型；DeepSeek OpenAI 兼容，接入简单

## D7 · 状态持久化：LangGraph Checkpoint（PostgresSaver）
- 日期：2026-10-17
- 背景：图含多次 LLM/工具调用，耗时长；需支持崩溃续跑、跨轮记忆、HITL
- 决定：`langgraph-checkpoint-postgres`（`AsyncPostgresSaver`），`thread_id = session_id`
- 放弃：InMemorySaver（重启即失）、自己写状态表（重复造轮子、易与图状态不一致）
- 影响：复用已有 PG；同 super-step 已完成 writes 不重跑，省 token；支持 time-travel 调试

## D8 · LLM 可靠性：超时 + 重试 + 熔断 + 降级隔离
- 日期：2026-10-17
- 背景：LLM 与外部工具是不可靠依赖，会超时/限流/5xx
- 决定：四件套——`wait_for` 超时、`tenacity` 指数退避重试（仅可重试错误）、轻量熔断器、工具级降级隔离
- 放弃：裸调用（雪崩）、无限重试（放大故障）、全局熔断（粒度太粗）
- 影响：局部失败不拖垮整图；主模型失败回退备用/模板，保证有输出

## D9 · 上下文管理：历史摘要压缩 + RAG topK=5
- 日期：2026-10-17
- 背景：多轮 + RAG 注入使上下文膨胀，撞窗口 / 烧钱
- 决定：保留最近 N=4 轮原文，更早轮次 LLM 摘要；RAG 固定注入 topK=5；tiktoken 预估预算
- 放弃：直接截断（丢约束）、全量注入（超窗/贵）
- 影响：控注入量、保关键偏好；摘要失败退化为截断

## D10 · 幻觉治理：源头 RAG + LLM-as-judge + 人工抽检
- 日期：2026-10-17
- 背景：LLM 会编造景点/营业时间/票价
- 决定：三道关——RAG grounding（无据不编）、独立 LLM-as-judge（与生成解耦）、定期人工抽检校准
- 放弃：仅靠生成模型自评（自评偏差大）、纯人工（不可扩展）
- 影响：可度量 `factual_consistency / grounded_rate`，反哺 prompt 与 rubric

## D11 · 可观测性：OpenTelemetry trace + 指标埋点
- 日期：2026-10-17
- 背景：Agent 多步黑盒，故障难定位、成本不透明
- 决定：OTel 每节点一个 span；埋点延迟 / token / cost / 工具成功率 / 回环次数；JSON 结构化日志贯穿 request_id
- 放弃：只打 print 日志（不可聚合、无链路）
- 影响：可定位"哪一步跑偏/变慢/烧钱"；与 checkpoint 配合做 time-travel

## D12 · 入口路由：Router 意图分流
- 日期：2026-10-17
- 背景：并非所有输入都需跑完整图（闲聊、信息不足）
- 决定：入口 router 分类 `intent`（chat / clarify / plan），条件边分流
- 放弃：一律跑全图（浪费 token、体验差）
- 影响：省 token；缺槽位时先追问；图入口从 START→planner 改为 START→router

## D13 · 人机协同：HITL interrupt
- 日期：2026-10-17
- 背景：执行前的任务清单可能跑偏，浪费一轮
- 决定：执行前 `interrupt()` 让用户确认/编辑任务清单，`Command(resume=...)` 续跑
- 放弃：全自动（跑偏成本高）
- 影响：依赖 checkpointer；SSE 增 `interrupt` 事件 + `/api/resume`

## D14 · 工具接入：高德 MCP（amap-maps）
- 日期：2026-10-17
- 背景：需 POI/路线/周边/天气，且希望体现工具协议标准化
- 决定：通过 MCP 客户端调用 amap-maps（`maps_text_search`/`maps_around_search`/`maps_direction_*`/`maps_distance`/`maps_weather`）
- 放弃：直连高德 HTTP（可用但无协议抽象，工具替换成本高）
- 影响：工具统一为 MCP 协议，易替换/扩展；需处理 MCP 连接与失败降级（§12.9）

## D15 · 缓存与降级数据源
- 日期：2026-10-17
- 背景：重复/相似 query 与外部依赖抖动
- 决定：Redis 语义缓存（embedding 相似度 >0.95，TTL 1h）；MCP/天气失败回退种子数据或缓存
- 放弃：无缓存（重复烧钱）、无降级（依赖挂了就整体失败）
- 影响：降延迟降成本；降级响应标注 `degraded: true`

## D16 · 对话接口方法：POST /api/chat
- 日期：2026-10-17
- 背景：SSE 需要带 Authorization header，且 message 可能较长
- 决定：POST + JSON body，前端 `fetch` + `ReadableStream` 解析
- 放弃：GET + query（长消息需编码、`EventSource` 不能带 header）
- 影响：统一 design / 接口契约为 POST

## D17 · Schema 迁移：Alembic
- 日期：2026-10-17
- 背景：`trips`/`prefs`/`docs` 及 checkpointer 表会演进
- 决定：Alembic 管理迁移，HNSW 索引写在迁移脚本
- 放弃：代码内裸跑 DDL（不可回滚、多环境漂移）
- 影响：`alembic upgrade head` 一键建/改表

---

## 模板

```markdown
## D{N} · {决策标题}
- 日期：YYYY-MM-DD
- 背景：{要解决什么问题}
- 决定：{选了什么}
- 放弃：{还有什么可选及为何不选}
- 影响：{代价 / 收益 / 后续}
```
