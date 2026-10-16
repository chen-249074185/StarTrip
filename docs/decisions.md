# 设计决策记录（ADR）

> 记录"为什么这么选"，面试可讲取舍。每条：背景 / 决定 / 放弃 / 影响。
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
