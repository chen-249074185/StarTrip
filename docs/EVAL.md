# StarTrip 评测

> 目标：把「行程规划好不好」拆成可重复的检索指标和生成指标，而不是只看 demo 效果。

## 1. 评测集

当前 `tests/eval/golden.json` 共 **12 条**，覆盖：

| 类别 | 说明 |
|---|---|
| `normal` | 常规 2 日游 |
| `multi_day` | 3 日游 |
| `budget` | 带预算约束 |

每条包含：

- `input`：用户自然语言需求
- `must_include` / `must_avoid`：必须出现 / 必须避开的景点
- `key_facts`：检索命中判定用的关键事实
- `golden_answer`：参考行程，用于 LLM-as-judge 的 coverage 评分
- `category`：评测分层

> 局限：12 条偏小，且关键词与知识库重合度较高，指标会偏乐观。

### 硬集（`tests/eval/golden_hard.json`）

额外 11 条，专门覆盖基础集不容易暴露的问题：

| 类别 | 数量 | 目的 |
|---|---:|---|
| `paraphrase` | 4 | 不直接出现关键词的改写 query |
| `no_answer` | 2 | 知识库没有的目的地，检查是否拒答 |
| `conflict` | 1 | 预算 100 必须去迪士尼，检查冲突处理 |
| `multi_city` / `family` / `budget` / `normal` | 4 | 多城市、带父母、预算、夜景等 |

> 本次已在 Docker PG/Redis + 51 条 docs + DashScope `text-embedding-v3` 环境实跑。

### 硬集 A/B 结果（11 条，9 条有答案 + 2 条 no-answer）

| 模式 | Recall@5 | MRR | key_fact_coverage | no-answer FP | 平均耗时 |
|---|---:|---:|---:|---:|---:|
| dense | **100.0%** | **1.000** | **100.0%** | 0.0% | 236.2 ms |
| sparse | 44.4% | 0.315 | 38.9% | 0.0% | 2.4 ms |
| hybrid | **100.0%** | **1.000** | **100.0%** | 0.0% | 212.4 ms |

> `dense_queries` 模拟 LLM 改写后的 query（含城市/景点），`keywords` 用用户原话里的近义词（如“江景/园林”而不是“外滩/豫园”）。  
> 结论：sparse-only 在改写 query 上明显不够；dense 已经能覆盖，hybrid 与 dense 持平。hybrid 的价值是关键词兜底，不是在这份集上“更高分”。

### 基础集 A/B

12 条基础集在 dense / sparse / hybrid 三种模式下都是 1.0——说明基础集太简单（query 与知识库关键词高度重合），不能用来证明混合检索的收益。

## 2. 检索层指标

脚本：`scripts/eval_retrieval.py`

| 指标 | 定义 |
|---|---|
| `Recall@K` | topK 结果中是否至少命中一个关键事实 |
| `MRR` | 第一个命中关键事实的排名的倒数均值 |
| `key_fact_coverage` | topK 文本覆盖的关键事实比例 |
| `no_answer_false_positive_rate` | 无答案 query 仍返回文档的比例 |
| `avg_latency_ms` | 单条检索平均耗时 |

### 当前结果（12 条）

| 指标 | 值 |
|---|---:|
| cases | 12 |
| Recall@5 | 1.0 |
| MRR | 1.0 |
| key_fact_coverage | 1.0 |
| no_answer_false_positive_rate | 0.0 |
| avg_latency_ms | 209.8 |

> 这个 1.0 不代表线上效果：当前 query 与知识库关键词重合度高，且没有 no-answer 样本。它的价值是建立基线，后续每次改检索都跑同一套集。

## 3. 端到端指标

脚本：`scripts/run_eval.py`，由独立 LLM-as-judge 打分。

| 指标 | 定义 |
|---|---|
| `factual_consistency` | 行程中的景点/门票/交通是否与证据一致 |
| `grounded_rate` | 行程中有证据支撑的比例 |
| `answer_coverage` | 与 `golden_answer` 关键事实的覆盖比例 |
| `format_valid_rate` | 是否符合固定 JSON schema |
| `constraint_include_rate` | `must_include` 命中率 |
| `constraint_avoid_hits` | 命中 `must_avoid` 的次数 |
| `avg_review_score` | Reviewer 5 维评分均值 |
| `feasibility_rate` | 行程通过确定性校验（时间/预算/重复/必去/避开/天数）的比例 |
| `time_conflict_rate` | 时间重叠 / 时间不合法比例 |
| `budget_overrun_rate` | 预算超支比例 |
| `duplicate_rate` | 重复景点比例 |
| `p50/p90/p99_latency_ms` | 端到端延迟分位数 |

### 当前结果（1 条 smoke）

| 指标 | 值 |
|---|---:|
| cases | 1 |
| factual_consistency | 0.6 |
| grounded_rate | 0.8 |
| answer_coverage | 0.6 |
| format_valid_rate | 1.0 |
| constraint_include_rate | 1.0 |
| avg_review_score | 88.0 |
| avg_latency_ms | 12510.7 |

> 只跑了 1 条 smoke（缺少完整 API Key / 知识库时用于验证链路），不能代表整体质量。完整 12 条需要在配好 PG、知识库、LLM/高德 Key 后运行。

## 4. 复现

```bash
# 检索层：混合检索
python -m scripts.eval_retrieval --md reports/retrieval.md

# 检索层 A/B：纯向量 vs 纯关键词 vs 混合
python -m scripts.eval_retrieval --mode dense --md reports/retrieval-dense.md
python -m scripts.eval_retrieval --mode sparse --md reports/retrieval-sparse.md
python -m scripts.eval_retrieval --mode hybrid --md reports/retrieval-hybrid.md

# 硬集
python -m scripts.eval_retrieval --golden tests/eval/golden_hard.json --md reports/retrieval-hard.md

# 端到端（需要 PG + 知识库 + Key）
python -m scripts.run_eval --md reports/eval.md

# 只跑前 3 条
python -m scripts.run_eval --limit 3 --md reports/eval-smoke.md
```

报告会写入 `reports/`，同时输出 JSON 和 Markdown。

## 5. 已知短板

- 评测集小，且 query 与知识库关键词重合度高，指标偏乐观。
- 没有 no-answer 样本，拒答能力未验证。
- 没有 dense-only / dense+sparse / +rerank 的 A/B 对比。
- 端到端只跑了 1 条 smoke，样本不足。
- LLM-as-judge 本身有偏差，需要人工抽检校准。

## 6. 下一步

1. 扩到 50+ 条，覆盖更多城市、天数、预算、偏好。
2. 加入改写 query、跨城市干扰、no-answer、冲突约束。
3. 做 dense-only vs hybrid 的 A/B，记录 Recall/MRR/延迟。
4. 把评测接进 CI（无 Key 时跑 mock/检索层，有 Key 时 nightly 跑端到端）。
5. 人工抽检 10% 样本，校准 LLM-as-judge。
