"""执行前确认节点（HITL）：暂停图，等待用户确认/编辑任务清单。

- `interrupt()` 依赖 checkpointer 保存暂停态（thread_id = session_id）
- 恢复时通过 `Command(resume={"tasks": [...]})` 覆盖原任务
- 用户取消全部任务 → cancelled=true，直接收尾，不执行任何工具
- 回环重试（retry_count > 1）不再重复打断，避免每轮都确认
"""

from __future__ import annotations

from langgraph.types import interrupt

from app.config import settings
from app.state import TripState
from app.tasks import sanitize_tasks


async def confirm(state: TripState) -> dict:
    tasks = sanitize_tasks(state.get("tasks") or [], max_tasks=settings.max_tasks)
    if not settings.hitl_enabled or not tasks or state.get("retry_count", 0) > 1:
        return {}

    decision = interrupt(
        {
            "tasks": tasks,
            "msg": "请确认要执行的工具任务（可取消勾选不需要的项；全部取消则不执行）",
        }
    )
    picked = decision.get("tasks") if isinstance(decision, dict) else None
    if picked is None:
        return {"tasks": tasks, "cancelled": False}

    cleaned = sanitize_tasks(picked, max_tasks=settings.max_tasks)
    if not cleaned:
        # 明确“全不选”= 取消，而不是回退到原始任务
        return {
            "tasks": [],
            "cancelled": True,
            "reply": "已取消本次工具执行。",
        }
    return {"tasks": cleaned, "cancelled": False}
