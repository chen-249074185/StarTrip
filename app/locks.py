"""进程内会话锁：防止同一个 thread 并发跑两张图。

LangGraph 的 checkpoint 以 thread_id 为粒度，两个请求同时写同一 thread
会互相覆盖。单实例下用 asyncio.Lock 挡住即可；多实例部署时应换成 Redis 锁
（README 的 Roadmap 已注明）。
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict

_MAX_LOCKS = 5000
_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()


def get_lock(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
        _prune()
    else:
        _locks.move_to_end(key)
    return lock


async def try_acquire(lock: asyncio.Lock) -> bool:
    """非阻塞获取；已锁则立刻返回 False（事件循环内 check+acquire 不会让出）。"""
    if lock.locked():
        return False
    await lock.acquire()
    return True


def release(lock: asyncio.Lock) -> None:
    if lock.locked():
        lock.release()


def _prune() -> None:
    if len(_locks) <= _MAX_LOCKS:
        return
    for key in list(_locks):
        if len(_locks) <= _MAX_LOCKS // 2:
            break
        if not _locks[key].locked():
            _locks.pop(key, None)
