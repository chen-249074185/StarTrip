"""LangGraph Checkpoint 持久化（PostgresSaver + 异步适配器）。

Windows 上 psycopg 异步连接与 MCP stdio 的事件循环策略冲突：
- MCP stdio 需要默认的 ProactorEventLoop（才能起子进程）
- psycopg async 需要 SelectorEventLoop（add_reader）

因此这里用**同步 PostgresSaver + asyncio.to_thread**：复用 `app.db.pg` 的同步连接池，
把 LangGraph 需要的 async 方法（aget_tuple / alist / aput / aput_writes）桥接到线程，
主事件循环保持 Proactor，MCP 与 Checkpoint 可共存。
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple
from langgraph.checkpoint.postgres import PostgresSaver

from app.db.pg import get_pool


class AsyncCheckpointAdapter(BaseCheckpointSaver):
    """把同步 PostgresSaver 包装成 AsyncCheckpointSaver 接口。"""

    def __init__(self, saver: PostgresSaver):
        super().__init__(serde=saver.serde)
        self._saver = saver

    async def aget_tuple(self, config: Any) -> CheckpointTuple | None:
        return await asyncio.to_thread(self._saver.get_tuple, config)

    async def alist(
        self,
        config: Any,
        *,
        filter: dict[str, Any] | None = None,
        before: Any = None,
        limit: int | None = None,
    ):
        def _list() -> list[CheckpointTuple]:
            return list(
                self._saver.list(config, filter=filter, before=before, limit=limit)
            )

        for item in await asyncio.to_thread(_list):
            yield item

    async def aput(
        self,
        config: Any,
        checkpoint: Any,
        metadata: Any,
        new_versions: Any,
    ) -> Any:
        return await asyncio.to_thread(
            self._saver.put, config, checkpoint, metadata, new_versions
        )

    async def aput_writes(
        self,
        config: Any,
        writes: Any,
        task_id: str,
        task_path: str = "",
    ) -> None:
        await asyncio.to_thread(
            self._saver.put_writes, config, writes, task_id, task_path
        )

    async def adelete_thread(self, thread_id: str) -> None:
        await asyncio.to_thread(self._saver.delete_thread, thread_id)


async def init_checkpointer() -> AsyncCheckpointAdapter:
    """建表并返回异步适配器；失败时由调用方降级到 InMemorySaver。"""
    saver = PostgresSaver(get_pool())
    await asyncio.to_thread(saver.setup)
    return AsyncCheckpointAdapter(saver)
