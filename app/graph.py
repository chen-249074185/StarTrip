from langgraph.graph import END, START, StateGraph

from app.nodes.chat_reply import chat_reply
from app.nodes.executor import executor
from app.nodes.planner import planner
from app.nodes.recommend import recommend
from app.nodes.retriever import retriever
from app.nodes.reviewer import reviewer
from app.nodes.router import router
from app.state import TripState

SCORE_THRESHOLD = 80   # 评分达标线
MAX_RETRY = 3          # 回环上限


# ===== 条件边 =====

def route_after_router(state: TripState) -> str:
    """chat → 保底回复；recommend → 推荐；plan → 规划。"""
    intent = state.get("intent")
    if intent == "chat":
        return "chat"
    if intent == "recommend":
        return "recommend"
    return "planner"


def route_after_review(state: TripState) -> str:
    """评分达标或达回环上限 → 结束；否则回 planner 重规划。"""
    score = state.get("score") or 0.0
    retry = state.get("retry_count", 0)
    if score >= SCORE_THRESHOLD or retry >= MAX_RETRY:
        return END
    return "planner"


# ===== 图装配 =====

def build_graph() -> StateGraph:
    g = StateGraph(TripState)
    g.add_node("router", router)
    g.add_node("chat", chat_reply)
    g.add_node("recommend", recommend)
    g.add_node("planner", planner)
    g.add_node("executor", executor)
    g.add_node("retriever", retriever)
    g.add_node("reviewer", reviewer)

    g.add_edge(START, "router")
    g.add_conditional_edges(
        "router",
        route_after_router,
        {"chat": "chat", "recommend": "recommend", "planner": "planner"},
    )
    g.add_edge("chat", END)
    g.add_edge("recommend", END)

    g.add_edge("planner", "executor")
    g.add_edge("executor", "retriever")
    g.add_edge("retriever", "reviewer")
    g.add_conditional_edges("reviewer", route_after_review, {"planner": "planner", END: END})

    return g


graph = build_graph().compile()
