from langgraph.graph import END, START, StateGraph

from app.nodes.executor import executor
from app.nodes.planner import planner
from app.nodes.retriever import retriever
from app.nodes.reviewer import reviewer
from app.state import TripState

SCORE_THRESHOLD = 80   # 评分达标线
MAX_RETRY = 3          # 回环上限


# ===== 条件边 =====

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
    g.add_node("planner", planner)
    g.add_node("executor", executor)
    g.add_node("retriever", retriever)
    g.add_node("reviewer", reviewer)

    g.add_edge(START, "planner")
    g.add_edge("planner", "executor")
    g.add_edge("executor", "retriever")
    g.add_edge("retriever", "reviewer")
    g.add_conditional_edges("reviewer", route_after_review, {"planner": "planner", END: END})

    return g


graph = build_graph().compile()
