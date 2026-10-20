"""离线评测：golden set → 跑图 → 独立 LLM-as-judge → 汇总报告。

用法（需 PG 已启动、知识库已构建、LLM/高德 key 已配置）：
    python -m scripts.run_eval
    python -m scripts.run_eval --limit 3 --out reports/eval-smoke.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from app.config import settings
from app.db.pg import close_pool, init_schema, open_pool
from app.eval.judge import judge_trip
from app.eval.metrics import aggregate, match_constraints
from app.graph import compile_graph
from app.tools import close_amap


async def run_case(graph, case: dict) -> dict:
    thread_id = f"eval-{case['id']}-{int(time.time() * 1000)}"
    config = {"configurable": {"thread_id": thread_id}}
    state = await graph.ainvoke(
        {"user_input": case["input"], "session_id": thread_id}, config
    )
    plan = state.get("trip_plan")
    evidence = {
        "tool_results": state.get("tool_results"),
        "rag_hints": state.get("rag_hints"),
    }
    judged = await judge_trip(case["input"], plan, evidence)
    return {
        "id": case["id"],
        "input": case["input"],
        "score": state.get("score"),
        "trip_plan": plan,
        "judge": judged,
        "constraints": match_constraints(plan, case),
    }


def failed_row(case: dict, error: Exception) -> dict:
    return {
        "id": case["id"],
        "input": case["input"],
        "score": None,
        "trip_plan": None,
        "judge": {
            "factual_consistency": 0.0,
            "grounded_rate": 0.0,
            "format_valid": False,
            "issues": [str(error)],
        },
        "constraints": match_constraints(None, case),
        "error": str(error),
    }


async def main(args: argparse.Namespace) -> None:
    open_pool()
    await init_schema()
    try:
        await _run(args)
    finally:
        await close_amap()
        close_pool()


async def _run(args: argparse.Namespace) -> None:
    cases = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[: args.limit]

    settings.hitl_enabled = False   # 评测全自动，不等待人工确认
    graph = compile_graph(InMemorySaver())

    rows: list[dict] = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']} ...")
        try:
            row = await run_case(graph, case)
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR: {e}")
            rows.append(failed_row(case, e))
            continue
        rows.append(row)
        print(f"  score={row['score']} judge={row['judge']}")

    summary = aggregate(rows)
    report = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "golden": str(args.golden),
        "summary": summary,
        "cases": rows,
    }
    out = (
        Path(args.out)
        if args.out
        else Path("reports") / f"eval-{time.strftime('%Y%m%d-%H%M%S')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("summary:", json.dumps(summary, ensure_ascii=False))
    print("report:", out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="StarTrip 离线评测")
    parser.add_argument("--golden", default="tests/eval/golden.json")
    parser.add_argument("--out", default="")
    parser.add_argument("--limit", type=int, default=0)
    asyncio.run(main(parser.parse_args()))
