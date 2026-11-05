"""检索层离线评测：固定 query → dense + sparse + RRF → Recall@K / MRR。

用法（需 PG 已启动、知识库已构建、DashScope key 已配置）：
    python -m scripts.eval_retrieval
    python -m scripts.eval_retrieval --limit 5 --topk 5 --md reports/retrieval.md

设计原则：
- 用 golden 里固定的 dense_queries / keywords，避免 LLM 改写带来的随机性；
- 没有 retrieval 字段时，退回 input 和 must_include，保证老数据也能跑；
- key_facts 为空视为“无答案样本”，单独统计误召回率。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.db.pg import close_pool, open_pool
from app.rag.search import dense_search, fetch_contents, rrf, sparse_search


def case_queries(case: dict) -> tuple[list[str], list[str], list[str]]:
    """取检索 query / 关键词 / 判定事实；兼容旧 golden 结构。"""
    retrieval = case.get("retrieval") or {}
    dense = retrieval.get("dense_queries") or [case.get("input", "")]
    keywords = retrieval.get("keywords") or case.get("must_include") or []
    facts = case.get("key_facts") or case.get("must_include") or []
    return (
        [q for q in dense if q],
        [k for k in keywords if k],
        [f for f in facts if f],
    )


def _doc_text(doc: dict) -> str:
    return f"{doc.get('title') or ''} {doc.get('content') or ''}"


def score_docs(docs: list[dict], facts: list[str]) -> dict[str, Any]:
    """计算 hit@K、MRR、关键事实覆盖率；facts 为空时返回无答案样本。"""
    if not facts:
        return {
            "hit": None,
            "mrr": None,
            "coverage": None,
            "matched": [],
            "doc_count": len(docs),
        }

    text = " ".join(_doc_text(doc) for doc in docs)
    matched = [fact for fact in facts if fact in text]

    ranks: list[int] = []
    for fact in facts:
        for index, doc in enumerate(docs, 1):
            if fact in _doc_text(doc):
                ranks.append(index)
                break

    return {
        "hit": bool(matched),
        "mrr": round(1.0 / min(ranks), 4) if ranks else 0.0,
        "coverage": round(len(matched) / len(facts), 4),
        "matched": matched,
        "doc_count": len(docs),
    }


async def run_case(case: dict, topk: int, mode: str = "hybrid") -> dict[str, Any]:
    dense_queries, keywords, facts = case_queries(case)
    started = time.perf_counter()
    if mode == "dense":
        dense_ids, sparse_ids = await dense_search(dense_queries, topn=20), []
    elif mode == "sparse":
        dense_ids, sparse_ids = [], await sparse_search(keywords, topn=20)
    else:
        dense_ids, sparse_ids = await asyncio.gather(
            dense_search(dense_queries, topn=20),
            sparse_search(keywords, topn=20),
        )
    fused = rrf(dense_ids, sparse_ids, topk=topk)
    docs = await fetch_contents(fused)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    scored = score_docs(docs, facts)
    return {
        "id": case.get("id", ""),
        "category": case.get("category", "uncategorized"),
        "input": case.get("input", ""),
        "dense_queries": dense_queries,
        "keywords": keywords,
        "key_facts": facts,
        "latency_ms": latency_ms,
        "topk": topk,
        "doc_ids": fused,
        "docs": [
            {"id": doc.get("id"), "title": doc.get("title"), "content": (doc.get("content") or "")[:300]}
            for doc in docs
        ],
        **scored,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answered = [row for row in rows if row["hit"] is not None]
    no_answer = [row for row in rows if row["hit"] is None]
    n = len(answered)

    recall = round(sum(1 for row in answered if row["hit"]) / n, 4) if n else 0.0
    mrr = round(sum(float(row["mrr"] or 0) for row in answered) / n, 4) if n else 0.0
    coverage = (
        round(sum(float(row["coverage"] or 0) for row in answered) / n, 4) if n else 0.0
    )
    latencies = [float(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None]
    false_positive = (
        round(sum(1 for row in no_answer if row["doc_count"] > 0) / len(no_answer), 4)
        if no_answer
        else 0.0
    )

    return {
        "cases": len(rows),
        "answered_cases": n,
        "no_answer_cases": len(no_answer),
        "recall@k": recall,
        "mrr": mrr,
        "key_fact_coverage": coverage,
        "no_answer_false_positive_rate": false_positive,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
    }


def write_markdown(report: dict, path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# StarTrip 检索评测报告",
        "",
        f"- 生成时间：{report['created_at']}",
        f"- golden：`{report['golden']}`",
        f"- topK：{report['topk']}",
        f"- 模式：{report.get('mode', 'hybrid')}",
        "",
        "## 汇总",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
    ]
    for key in (
        "cases",
        "answered_cases",
        "no_answer_cases",
        "recall@k",
        "mrr",
        "key_fact_coverage",
        "no_answer_false_positive_rate",
        "avg_latency_ms",
    ):
        lines.append(f"| {key} | {summary.get(key, '')} |")
    lines += [
        "",
        "## 逐条",
        "",
        "| id | category | hit@K | MRR | coverage | latency(ms) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in report["cases"]:
        lines.append(
            f"| {row['id']} | {row['category']} | {row['hit']} | "
            f"{row['mrr']} | {row['coverage']} | {row['latency_ms']} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _run(args: argparse.Namespace) -> None:
    cases = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[: args.limit]

    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, 1):
        print(f"[{index}/{len(cases)}] {case.get('id')} ...")
        try:
            row = await run_case(case, args.topk, args.mode)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}")
            rows.append(
                {
                    "id": case.get("id", ""),
                    "category": case.get("category", "uncategorized"),
                    "input": case.get("input", ""),
                    "hit": None,
                    "mrr": None,
                    "coverage": None,
                    "doc_count": 0,
                    "latency_ms": None,
                    "error": str(exc),
                }
            )
            continue
        rows.append(row)
        print(f"  hit={row['hit']} mrr={row['mrr']} coverage={row['coverage']}")

    report = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "golden": str(args.golden),
        "topk": args.topk,
        "mode": args.mode,
        "summary": summarize(rows),
        "cases": rows,
    }
    out = (
        Path(args.out)
        if args.out
        else Path("reports") / f"retrieval-{time.strftime('%Y%m%d-%H%M%S')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md:
        md_path = out.with_suffix(".md") if args.md == "auto" else Path(args.md)
        write_markdown(report, md_path)
        print("markdown:", md_path)
    print("summary:", json.dumps(report["summary"], ensure_ascii=False))
    print("report:", out)


async def main(args: argparse.Namespace) -> None:
    open_pool()
    try:
        await _run(args)
    finally:
        close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="StarTrip 检索层离线评测")
    parser.add_argument("--golden", default="tests/eval/golden.json")
    parser.add_argument("--out", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--topk", type=int, default=5)
    parser.add_argument(
        "--mode",
        choices=("hybrid", "dense", "sparse"),
        default="hybrid",
        help="检索模式：hybrid=dense+sparse+RRF，dense=纯向量，sparse=纯关键词",
    )
    parser.add_argument(
        "--md",
        nargs="?",
        const="auto",
        default="",
        help="同时输出 Markdown 报告；不传值则与 JSON 同目录",
    )
    asyncio.run(main(parser.parse_args()))
