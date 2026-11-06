from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.nodes.chat_reply import chat_reply
from app.nodes.confirm import confirm
from app.nodes.executor import executor
from app.nodes.persist import persist
from app.nodes.planner import planner
from app.nodes.recommend import recommend
from app.nodes.remember import remember
from app.nodes.retriever import retriever
from app.nodes.reviewer import reviewer
from app.nodes.router import router
from app.state import TripState

SCORE_THRESHOLD = 80   # 评分达标线
MAX_PLANNER_CALLS = 3  # 规划次数上限（首次 + 2 次重规划）
MAX_REVIEW_FAILURES = 2  # Reviewer LLM 连续失败达到该次数直接收尾，避免空转


# ===== 条件边 =====

def route_after_router(state: TripState) -> str:
    """chat → 保底回复；recommend → 推荐；plan → 规划。"""
    intent = state.get("intent")
    if intent == "chat":
        return "chat"
    if intent == "recommend":
        return "recommend"
    return "planner"


def route_after_confirm(state: TripState) -> str:
    """用户取消全部任务 → 直接收尾；否则执行。"""
    if state.get("cancelled"):
        return "remember"
    return "executor"


def route_after_review(state: TripState) -> str:
    """评分达标 / 达规划上限 / 无有效反馈 / LLM 连续失败 → 收尾；否则回 planner。"""
    score = state.get("score") or 0.0
    retry = state.get("retry_count", 0)
    if score >= SCORE_THRESHOLD or retry >= MAX_PLANNER_CALLS:
        return "remember"
    if int(state.get("review_failures", 0)) >= MAX_REVIEW_FAILURES:
        return "remember"
    # 没有 feedback 说明模型自己也不知道哪里不好，再规划一次大概率还是同一版
    if not state.get("feedback"):
        return "remember"
    return "planner"


# ===== 图装配 =====

def build_graph() -> StateGraph:
    g = StateGraph(TripState)
    g.add_node("router", router)
    g.add_node("chat", chat_reply)
    g.add_node("recommend", recommend)
    g.add_node("planner", planner)
    g.add_node("confirm", confirm)
    g.add_node("executor", executor)
    g.add_node("retriever", retriever)
    g.add_node("reviewer", reviewer)
    g.add_node("remember", remember)
    g.add_node("persist", persist)

    g.add_edge(START, "router")
    g.add_conditional_edges(
        "router",
        route_after_router,
        {"chat": "chat", "recommend": "recommend", "planner": "planner"},
    )
    g.add_edge("chat", "remember")
    g.add_edge("recommend", "remember")

    g.add_edge("planner", "confirm")
    g.add_conditional_edges(
        "confirm",
        route_after_confirm,
        {"executor": "executor", "remember": "remember"},
    )
    g.add_edge("executor", "retriever")
    g.add_edge("retriever", "reviewer")
    g.add_conditional_edges(
        "reviewer",
        route_after_review,
        {"planner": "planner", "remember": "remember"},
    )
    g.add_edge("remember", "persist")
    g.add_edge("persist", END)

    return g


_checkpointer_kind = "memory"


def compile_graph(checkpointer=None):
    """按指定 checkpointer 编译图（无则纯内存、不跨进程）。"""
    return build_graph().compile(checkpointer=checkpointer)


def set_checkpointer(checkpointer, kind: str = "postgres") -> None:
    """启动期切换 checkpointer（PG 就绪时用 PostgresSaver）。"""
    global graph, _checkpointer_kind
    graph = compile_graph(checkpointer)
    _checkpointer_kind = kind


def checkpointer_kind() -> str:
    return _checkpointer_kind


# 默认用内存 checkpointer：PG 未就绪时仍支持进程内多轮；启动后再切到 PG
graph = compile_graph(InMemorySaver())
