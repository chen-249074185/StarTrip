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
from app.grounding import ground_plan
from app.tools import close_amap
from app.validate import validate_plan


async def run_case(graph, case: dict) -> dict:
    thread_id = f"eval-{case['id']}-{int(time.time() * 1000)}"
    config = {"configurable": {"thread_id": thread_id}}
    started = time.perf_counter()
    state = await graph.ainvoke(
        {"user_input": case["input"], "session_id": thread_id}, config
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    plan = state.get("trip_plan")
    evidence = {
        "tool_results": state.get("tool_results"),
        "rag_hints": state.get("rag_hints"),
    }
    judged = await judge_trip(
        case["input"],
        plan,
        evidence,
        golden_answer=case.get("golden_answer"),
    )
    validation = validate_plan(
        plan,
        user_input=case["input"],
        must_include=case.get("must_include"),
        must_avoid=case.get("must_avoid"),
    )
    grounding = ground_plan(plan, state.get("tool_results"), state.get("rag_hints"))
    return {
        "id": case["id"],
        "category": case.get("category", "uncategorized"),
        "input": case["input"],
        "score": state.get("score"),
        "trip_plan": plan,
        "judge": judged,
        "constraints": match_constraints(plan, case),
        "validation": validation.to_dict(),
        "grounding": grounding,
        "latency_ms": latency_ms,
    }


def failed_row(case: dict, error: Exception) -> dict:
    return {
        "id": case["id"],
        "category": case.get("category", "uncategorized"),
        "input": case["input"],
        "score": None,
        "trip_plan": None,
        "judge": {
            "factual_consistency": 0.0,
            "grounded_rate": 0.0,
            "answer_coverage": 0.0,
            "format_valid": False,
            "issues": [str(error)],
        },
        "constraints": match_constraints(None, case),
        "validation": {
            "ok": False,
            "errors": [str(error)],
            "warnings": [],
            "checks": {},
            "metrics": {},
        },
        "grounding": {
            "applicable": False,
            "total": 0,
            "grounded": 0,
            "ungrounded": [],
            "ratio": 0.0,
        },
        "latency_ms": None,
        "error": str(error),
    }


def write_markdown(report: dict, path: Path) -> None:
    """把 JSON 报告压成一页可读的 Markdown。"""
    summary = report["summary"]
    lines = [
        "# StarTrip 离线评测报告",
        "",
        f"- 生成时间：{report['created_at']}",
        f"- golden：`{report['golden']}`",
        f"- 用例数：{summary.get('cases', 0)}",
        "",
        "## 汇总指标",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
    ]
    for key in (
        "factual_consistency",
        "grounded_rate",
        "answer_coverage",
        "format_valid_rate",
        "constraint_include_rate",
        "constraint_avoid_hits",
        "feasibility_rate",
        "time_conflict_rate",
        "budget_overrun_rate",
        "duplicate_rate",
        "avg_review_score",
        "score_calibration_mae",
        "avg_ungrounded_ratio",
        "error_cases",
        "avg_latency_ms",
        "p50_latency_ms",
        "p90_latency_ms",
        "p99_latency_ms",
    ):
        lines.append(f"| {key} | {summary.get(key, '')} |")
    lines += [
        "",
        "## 逐条结果",
        "",
        "| id | category | score | feasible | time | budget | factual | grounded | coverage | format | include | latency(ms) | error |",
        "|---|---|---:|---|---|---|---:|---:|---:|---|---:|---:|---|",
    ]
    for row in report["cases"]:
        judge = row.get("judge", {})
        constraints = row.get("constraints", {})
        validation = row.get("validation") or {}
        checks = validation.get("checks") or {}
        include = f"{len(constraints.get('include_hits', []))}/{len(constraints.get('include_required', []))}"
        lines.append(
            "| {id} | {cat} | {score} | {ok} | {time} | {budget} | {factual} | {grounded} | {coverage} | {fmt} | {inc} | {lat} | {err} |".format(
                id=row.get("id", ""),
                cat=row.get("category", ""),
                score=row.get("score", ""),
                ok=validation.get("ok", ""),
                time=checks.get("time", ""),
                budget=checks.get("budget", ""),
                factual=judge.get("factual_consistency", ""),
                grounded=judge.get("grounded_rate", ""),
                coverage=judge.get("answer_coverage", ""),
                fmt=judge.get("format_valid", ""),
                inc=include,
                lat=row.get("latency_ms", ""),
                err=(row.get("error") or "").replace("|", "/")[:80],
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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

    settings.hitl_enabled = False          # 评测全自动，不等待人工确认
    settings.trip_persist_enabled = False  # 不污染线上 trips 表
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
    if args.md:
        md_path = out.with_suffix(".md") if args.md == "auto" else Path(args.md)
        write_markdown(report, md_path)
        print("markdown:", md_path)
    print("summary:", json.dumps(summary, ensure_ascii=False))
    print("report:", out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="StarTrip 离线评测")
    parser.add_argument("--golden", default="tests/eval/golden.json")
    parser.add_argument("--out", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--md",
        nargs="?",
        const="auto",
        default="",
        help="同时输出 Markdown 报告；不传值则与 JSON 同目录",
    )
    asyncio.run(main(parser.parse_args()))
