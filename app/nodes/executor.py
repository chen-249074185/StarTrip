"""执行节点：并发调度工具并收集结果。

- `asyncio.gather(return_exceptions=True)`：单工具失败不拖垮整节点
- 每工具超时：`asyncio.wait_for`
- 同名工具结果聚合为列表（防覆盖）
- 工具未注册 / 调用失败 / 超时 → 记为 {"error": ...}（降级，不抛断）
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.config import settings
from app.observability import get_tracer
from app.resilience import CircuitOpenError, call_resilient
from app.state import TripState
from app.tools import get_tool


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
        return result
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


async def executor(state: TripState) -> dict:
    """并发执行 tasks，按工具名聚合结果。"""
    plan = state.get("tasks", [])
    if not plan:
        return {"tool_results": {}}

    results = await asyncio.gather(
        *[call_tool_safe(step) for step in plan],
        return_exceptions=True,
    )

    grouped: dict[str, list] = {}
    for step, r in zip(plan, results):
        name = step.get("tool", "unknown")
        if isinstance(r, BaseException):
            r = {"error": str(r)}
        grouped.setdefault(name, []).append(r)
    return {"tool_results": grouped}
