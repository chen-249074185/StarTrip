"""会话锁：同一 thread 只能有一个请求在跑。"""

from __future__ import annotations

from app.locks import get_lock, release, try_acquire


async def test_lock_blocks_second_holder():
    lock = get_lock("thread-lock-test")
    assert await try_acquire(lock) is True
    assert await try_acquire(lock) is False
    release(lock)
    assert await try_acquire(lock) is True
    release(lock)


async def test_different_threads_do_not_block():
    left = get_lock("thread-a")
    right = get_lock("thread-b")
    assert await try_acquire(left) is True
    assert await try_acquire(right) is True
    release(left)
    release(right)
