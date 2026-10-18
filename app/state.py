from typing import TypedDict


class TripState(TypedDict, total=False):
    """LangGraph 图共享状态。字段对齐 docs/接口契约.md 第 1 节。

    total=False：允许节点只返回自己更新的字段（LangGraph 按字段合并）。
    """

    # ===== 输入 =====
    user_input: str              # 原始需求
    intent: str                  # 路由判定：chat / clarify / plan
    history: list[dict]          # 多轮对话历史（经摘要压缩）
    session_id: str              # 会话 ID（= checkpoint thread_id）

    # ===== 规划 =====
    tasks: list[dict]            # 规划节点输出的任务列表

    # ===== 执行 =====
    tool_results: dict           # 执行节点收集的工具结果（按工具名聚合为列表）

    # ===== 检索 =====
    rag_hints: list[str]         # RAG 检索补充

    # ===== 审查 =====
    trip_plan: dict | None       # 行程方案
    score: float | None          # 审查评分（0~100）
    feedback: str | None         # 审查不达标原因（回环输入）

    # ===== 控制 =====
    retry_count: int             # 回环已用次数，上限 3
