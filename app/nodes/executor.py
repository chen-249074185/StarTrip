"""执行节点：并发调度工具并收集结果。

- `asyncio.gather(return_exceptions=True)`：单工具失败不拖垮整节点
- 每工具超时：`asyncio.wait_for`
- 单轮总预算：`executor_deadline`
- 同名工具结果聚合为列表（防覆盖），并限制条数/长度，避免 checkpoint 膨胀
- 工具未注册 / 调用失败 / 超时 → 记为 {"error": ...}（降级，不抛断）
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.config import settings
from app.observability import get_tracer
from app.resilience import CircuitOpenError, call_resilient
from app.state import TripState
from app.tasks import sanitize_tasks
from app.tools import all_tool_names, get_tool


def _trim(result: Any) -> Any:
    """单条结果限长：字符串截断，列表限量；保持结构可解析。"""
    if isinstance(result, str):
        return result[: settings.max_tool_result_chars]
    if isinstance(result, list):
        return result[: settings.max_tool_results_per_tool]
    return result


async def call_tool_safe(step: dict) -> Any:
    """调用单个工具：超时 + 重试 + 按工具熔断，失败降级为 error 字典。"""
    name = step.get("tool")
    args = step.get("args") or {}
    fn = get_tool(name) if name else None
    if fn is None:
        return {"error": f"未注册的工具: {name}"}

    async def _call() -> Any:
        return await fn(args)

    span = get_tracer().start_span(f"tool.{name}")
    span.set_attribute("tool.name", name)
    try:
        result = await call_resilient(
            f"tool:{name}",
            _call,
            timeout=settings.tool_timeout,
            attempts=settings.tool_max_retries,
            failure_threshold=settings.breaker_failure_threshold,
            reset_timeout=settings.breaker_reset_timeout,
        )
        span.set_attribute("tool.status", "ok")
        return _trim(result)
    except CircuitOpenError:
        span.set_attribute("tool.status", "circuit_open")
        return {"error": f"工具熔断中: {name}"}
    except TimeoutError:
        span.set_attribute("tool.status", "timeout")
        return {"error": f"工具超时({settings.tool_timeout}s): {name}"}
    except Exception as e:  # noqa: BLE001
        span.set_attribute("tool.status", "error")
        span.record_exception(e)
        return {"error": f"工具失败 {name}: {e}"}
    finally:
        span.end()


async def _run_all(plan: list[dict]) -> list[Any]:
    """并发执行，并给整轮一个总预算；超时的任务单独标记，不拖死请求。"""
    jobs = [asyncio.create_task(call_tool_safe(step)) for step in plan]
    try:
        done, pending = await asyncio.wait(
            jobs, timeout=settings.executor_deadline
        )
    except asyncio.CancelledError:
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        raise

    for job in pending:
        job.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    results: list[Any] = []
    for job in jobs:
        if job in done and not job.cancelled():
            try:
                results.append(job.result())
            except Exception as e:  # noqa: BLE001
                results.append({"error": str(e)})
        else:
            results.append({"error": "工具执行超出单轮总预算"})
    return results


async def executor(state: TripState) -> dict:
    """并发执行 tasks，按工具名聚合结果。"""
    plan = sanitize_tasks(
        state.get("tasks", []),
        allowed_tools=set(all_tool_names()),
        max_tasks=settings.max_tasks,
    )
    if not plan:
        return {"tool_results": {}}

    results = await _run_all(plan)

    grouped: dict[str, list] = {}
    for step, result in zip(plan, results):
        name = step.get("tool", "unknown")
        bucket = grouped.setdefault(name, [])
        if len(bucket) < settings.max_tool_results_per_tool:
            bucket.append(result)
    return {"tool_results": grouped}
