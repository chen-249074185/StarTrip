"""检索评测：query 兼容、命中/MRR/覆盖率、汇总。"""

from __future__ import annotations

from scripts.eval_retrieval import case_queries, score_docs, summarize


def test_case_queries_falls_back_to_input_and_must_include():
    dense, keywords, facts = case_queries(
        {"input": "上海两日游", "must_include": ["外滩", "豫园"]}
    )
    assert dense == ["上海两日游"]
    assert keywords == ["外滩", "豫园"]
    assert facts == ["外滩", "豫园"]


def test_case_queries_uses_explicit_retrieval_block():
    dense, keywords, facts = case_queries(
        {
            "input": "上海两日游",
            "retrieval": {"dense_queries": ["上海 景点"], "keywords": ["外滩"]},
            "key_facts": ["外滩"],
        }
    )
    assert dense == ["上海 景点"]
    assert keywords == ["外滩"]
    assert facts == ["外滩"]


def test_score_docs_hit_mrr_and_coverage():
    docs = [
        {"title": "上海", "content": "外滩夜景"},
        {"title": "上海", "content": "豫园和城隍庙"},
    ]
    result = score_docs(docs, ["外滩", "豫园", "迪士尼"])
    assert result["hit"] is True
    assert result["mrr"] == 1.0
    assert result["coverage"] == 0.6667
    assert result["matched"] == ["外滩", "豫园"]


def test_score_docs_no_answer_sample():
    result = score_docs([{"title": "x", "content": "无关内容"}], [])
    assert result["hit"] is None
    assert result["mrr"] is None
    assert result["coverage"] is None
    assert result["doc_count"] == 1


def test_summarize_recall_mrr_and_false_positive():
    rows = [
        {"hit": True, "mrr": 1.0, "coverage": 1.0, "latency_ms": 10, "doc_count": 5},
        {"hit": False, "mrr": 0.0, "coverage": 0.0, "latency_ms": 20, "doc_count": 5},
        {"hit": None, "mrr": None, "coverage": None, "latency_ms": 30, "doc_count": 5},
        {"hit": None, "mrr": None, "coverage": None, "latency_ms": 40, "doc_count": 0},
    ]
    summary = summarize(rows)
    assert summary["cases"] == 4
    assert summary["answered_cases"] == 2
    assert summary["no_answer_cases"] == 2
    assert summary["recall@k"] == 0.5
    assert summary["mrr"] == 0.5
    assert summary["no_answer_false_positive_rate"] == 0.5
    assert summary["avg_latency_ms"] == 25.0
