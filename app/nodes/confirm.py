"""执行前确认节点（HITL）：暂停图，等待用户确认/编辑任务清单。

- `interrupt()` 依赖 checkpointer 保存暂停态（thread_id = session_id）
- 恢复时通过 `Command(resume={"tasks": [...]})` 覆盖原任务
- 回环重试（retry_count > 1）不再重复打断，避免每轮都确认
"""

from __future__ import annotations

from langgraph.types import interrupt

from app.config import settings
from app.state import TripState


async def confirm(state: TripState) -> dict:
    tasks = state.get("tasks") or []
    if not settings.hitl_enabled or not tasks or state.get("retry_count", 0) > 1:
        return {}

    decision = interrupt(
        {
            "tasks": tasks,
            "msg": "请确认要执行的工具任务（可取消勾选不需要的项）",
        }
    )
    picked = decision.get("tasks") if isinstance(decision, dict) else None
    return {"tasks": picked or tasks}
