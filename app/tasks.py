"""工具任务清单的清洗与上限控制。

LLM 会编工具名、传奇怪参数，HITL 恢复时客户端也可能塞大量任务。
这里统一做“白名单 + 参数类型收敛 + 去重 + 限量”，planner/executor/resume 共用。
"""

from __future__ import annotations

import json
from typing import Any

MAX_TASKS = 12


def sanitize_args(args: Any, *, max_keys: int = 20, max_text: int = 500) -> dict[str, Any]:
    """只保留 JSON 标量参数，限制键数量和字符串长度。"""
    if not isinstance(args, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in list(args.items())[:max_keys]:
        if not isinstance(key, str) or not key or len(key) > 64:
            continue
        if isinstance(value, str):
            out[key] = value[:max_text]
        elif isinstance(value, (int, float, bool)) or value is None:
            out[key] = value
        # 嵌套对象/数组直接丢弃：当前所有工具都只接受标量参数
    return out


def sanitize_tasks(
    tasks: Any,
    *,
    allowed_tools: set[str] | None = None,
    max_tasks: int = MAX_TASKS,
) -> list[dict[str, Any]]:
    """过滤非法工具/非法参数，按 (tool,args) 去重，并截断到上限。"""
    if not isinstance(tasks, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in tasks:
        if not isinstance(raw, dict):
            continue
        tool = raw.get("tool")
        if not isinstance(tool, str) or not tool:
            continue
        if allowed_tools is not None and tool not in allowed_tools:
            continue
        args = sanitize_args(raw.get("args"))
        fingerprint = tool + "|" + json.dumps(args, ensure_ascii=False, sort_keys=True)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        out.append({"tool": tool, "args": args})
        if len(out) >= max(1, max_tasks):
            break
    return out
