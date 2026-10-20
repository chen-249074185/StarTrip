"""可靠性四件套：超时 / 重试 / 熔断 / 降级隔离。

- 超时：`asyncio.wait_for` 包住单次调用（LLM 另有 httpx 连接/读取超时）
- 重试：tenacity 指数退避 + 抖动，只重试可重试错误（429 / 5xx / 超时 / 连接失败）
- 熔断：连续失败 N 次 → 打开 reset_timeout 秒 → 半开探测一次，成功即闭合
- 降级：熔断打开时抛 `CircuitOpenError`，调用方（节点/executor）走兜底逻辑

熔断器按依赖名注册（`llm:primary` / `embedding:dashscope` / `tool:maps_weather`），
粒度到具体依赖，避免一个工具挂掉拖垮全部调用。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import TypeVar

import openai
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """熔断器打开：快速失败，交给调用方降级。"""


class TransientError(RuntimeError):
    """可重试的临时错误（第三方 SDK 非 openai 异常时用）。"""


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """轻量三态熔断器（closed / open / half-open）。"""

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
    ) -> None:
        self.name = name
        self.failure_threshold = max(1, failure_threshold)
        self.reset_timeout = max(0.0, reset_timeout)
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._probing = False
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failures(self) -> int:
        return self._failures

    async def before_call(self) -> None:
        """放行调用；熔断打开则抛 CircuitOpenError（半开时只放一个探测请求）。"""
        async with self._lock:
            if self._state is CircuitState.OPEN:
                if time.monotonic() - self._opened_at < self.reset_timeout:
                    raise CircuitOpenError(f"{self.name} 熔断中，请稍后重试")
                self._state = CircuitState.HALF_OPEN
                self._probing = False
            if self._state is CircuitState.HALF_OPEN:
                if self._probing:
                    raise CircuitOpenError(f"{self.name} 半开探测中，请稍后重试")
                self._probing = True

    async def record_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._state = CircuitState.CLOSED
            self._probing = False
            self._opened_at = 0.0

    async def record_failure(self) -> None:
        async with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._trip()
            elif self._state is CircuitState.CLOSED:
                self._failures += 1
                if self._failures >= self.failure_threshold:
                    self._trip()

    async def record_abort(self) -> None:
        """调用被取消：只释放半开探测位，不计成功/失败。"""
        async with self._lock:
            self._probing = False

    def _trip(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()
        self._probing = False

    def snapshot(self) -> dict:
        return {"state": self._state.value, "failures": self._failures}


# ===== 全局注册表 =====

_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(
    name: str,
    *,
    failure_threshold: int = 5,
    reset_timeout: float = 30.0,
) -> CircuitBreaker:
    """按名称取熔断器（首次创建后复用，参数只在创建时生效）。"""
    breaker = _breakers.get(name)
    if breaker is None:
        breaker = CircuitBreaker(
            name,
            failure_threshold=failure_threshold,
            reset_timeout=reset_timeout,
        )
        _breakers[name] = breaker
    return breaker


def breaker_snapshot() -> dict[str, dict]:
    return {name: b.snapshot() for name, b in sorted(_breakers.items())}


def reset_breakers() -> None:
    """测试/运维用：丢弃所有熔断状态。"""
    _breakers.clear()


# ===== 重试判定 =====

def is_retryable(exc: BaseException) -> bool:
    """只重试瞬时错误：超时 / 连接失败 / 429 / 5xx；4xx 等直接失败。"""
    if isinstance(exc, (TimeoutError, ConnectionError, TransientError)):
        return True
    if isinstance(exc, openai.APIConnectionError):   # 含 APITimeoutError
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


async def _call_with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    timeout: float | None,
) -> T:
    async def _once() -> T:
        coro = fn()
        if timeout is None:
            return await coro
        return await asyncio.wait_for(coro, timeout)

    retryer = AsyncRetrying(
        stop=stop_after_attempt(max(1, attempts)),
        wait=wait_exponential_jitter(multiplier=0.5, max=8.0, jitter=0.5),
        retry=retry_if_exception(is_retryable),
        reraise=True,
    )
    return await retryer(_once)


async def call_resilient(
    name: str,
    fn: Callable[[], Awaitable[T]],
    *,
    timeout: float | None = None,
    attempts: int = 3,
    failure_threshold: int = 5,
    reset_timeout: float = 30.0,
) -> T:
    """带超时 / 重试 / 熔断的调用入口。熔断打开时抛 CircuitOpenError。"""
    breaker = get_breaker(
        name,
        failure_threshold=failure_threshold,
        reset_timeout=reset_timeout,
    )
    await breaker.before_call()
    try:
        result = await _call_with_retry(fn, attempts=attempts, timeout=timeout)
    except asyncio.CancelledError:
        await breaker.record_abort()
        raise
    except Exception:
        await breaker.record_failure()
        raise
    await breaker.record_success()
    return result
