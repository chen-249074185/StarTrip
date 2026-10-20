"""对话历史工具：追加、去重、裁剪、格式化。

只保留最近 HISTORY_LIMIT 条消息（约 5 轮），单条截断到 MAX_CONTENT，
防止 Checkpoint 状态与后续 prompt 无限膨胀。
"""

from __future__ import annotations

HISTORY_LIMIT = 10
MAX_CONTENT = 800
PROMPT_CONTENT = 300


def trim_history(history: list[dict]) -> list[dict]:
    return history[-HISTORY_LIMIT:]


def append_message(history: list[dict], role: str, content: str) -> list[dict]:
    """追加一条消息；连续重复内容不重复记。"""
    content = (content or "").strip()
    if not content:
        return trim_history(list(history))
    content = content[:MAX_CONTENT]
    if (
        history
        and history[-1].get("role") == role
        and history[-1].get("content") == content
    ):
        return trim_history(list(history))
    return trim_history([*history, {"role": role, "content": content}])


def format_history(history: list[dict], limit: int = 6) -> str:
    """压成 prompt 里的对话文本（最近 limit 条）。"""
    rows: list[str] = []
    for msg in history[-limit:]:
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        role = "用户" if msg.get("role") == "user" else "助手"
        rows.append(f"{role}: {content[:PROMPT_CONTENT]}")
    return "\n".join(rows)


def prior_history(history: list[dict], limit: int = 6) -> str:
    """只取当前用户句之前的上下文（router 已把当前句追加进 history）。"""
    if history and history[-1].get("role") == "user":
        history = history[:-1]
    return format_history(history, limit=limit)
