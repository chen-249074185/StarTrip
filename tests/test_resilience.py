"""可靠性四件套单测：熔断三态 / 超时 / 重试分类 / 备用模型降级。"""

from __future__ import annotations

import asyncio

import httpx2
import openai
import pytest

from app import llm, resilience
from app.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    TransientError,
    call_resilient,
    is_retryable,
)


@pytest.fixture(autouse=True)
def _clean_breakers():
    resilience.reset_breakers()
    yield
    resilience.reset_breakers()


def _status_error(code: int) -> openai.APIStatusError:
    request = httpx2.Request("POST", "https://example.com")
    response = httpx2.Response(code, request=request)
    return openai.APIStatusError("boom", response=response, body=None)


def test_is_retryable_only_transient():
    assert is_retryable(TimeoutError())
    assert is_retryable(ConnectionError())
    assert is_retryable(TransientError())
    assert is_retryable(_status_error(429))
    assert is_retryable(_status_error(503))
    assert not is_retryable(_status_error(400))
    assert not is_retryable(ValueError())


async def test_breaker_opens_after_threshold():
    breaker = CircuitBreaker("t", failure_threshold=2, reset_timeout=60)
    await breaker.before_call()
    await breaker.record_failure()
    assert breaker.state is CircuitState.CLOSED

    await breaker.before_call()
    await breaker.record_failure()
    assert breaker.state is CircuitState.OPEN

    with pytest.raises(CircuitOpenError):
        await breaker.before_call()


async def test_half_open_success_closes():
    breaker = CircuitBreaker("t", failure_threshold=1, reset_timeout=0.01)
    await breaker.before_call()
    await breaker.record_failure()
    assert breaker.state is CircuitState.OPEN

    await asyncio.sleep(0.02)
    await breaker.before_call()
    assert breaker.state is CircuitState.HALF_OPEN

    await breaker.record_success()
    assert breaker.state is CircuitState.CLOSED
    assert breaker.failures == 0


async def test_half_open_failure_reopens():
    breaker = CircuitBreaker("t", failure_threshold=1, reset_timeout=0.01)
    await breaker.before_call()
    await breaker.record_failure()

    await asyncio.sleep(0.02)
    await breaker.before_call()
    assert breaker.state is CircuitState.HALF_OPEN

    await breaker.record_failure()
    assert breaker.state is CircuitState.OPEN


async def test_retry_then_success():
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("timeout")
        return "ok"

    result = await call_resilient("test:retry", flaky, timeout=1, attempts=3)
    assert result == "ok"
    assert calls == 3
    assert resilience.get_breaker("test:retry").state is CircuitState.CLOSED


async def test_non_retryable_fails_fast():
    calls = 0

    async def bad():
        nonlocal calls
        calls += 1
        raise ValueError("bad")

    with pytest.raises(ValueError):
        await call_resilient("test:bad", bad, attempts=3)
    assert calls == 1
    assert resilience.get_breaker("test:bad").failures == 1


async def test_timeout_recorded_as_failure():
    async def slow():
        await asyncio.sleep(1)

    with pytest.raises(TimeoutError):
        await call_resilient("test:timeout", slow, timeout=0.01, attempts=1)
    assert resilience.get_breaker("test:timeout").failures == 1


async def test_open_circuit_fast_fails_without_call():
    async def fail():
        raise ValueError("down")

    with pytest.raises(ValueError):
        await call_resilient(
            "test:open",
            fail,
            attempts=1,
            failure_threshold=1,
            reset_timeout=60,
        )

    calls = 0

    async def ok():
        nonlocal calls
        calls += 1
        return "ok"

    with pytest.raises(CircuitOpenError):
        await call_resilient("test:open", ok)
    assert calls == 0


async def test_chat_falls_back_to_secondary_model(monkeypatch):
    calls: list[str] = []

    async def fake_chat_once(model, messages, kwargs):
        calls.append(model)
        if model == llm.settings.deepseek_model:
            raise ValueError("primary down")
        return "backup reply"

    monkeypatch.setattr(llm, "_chat_once", fake_chat_once)
    monkeypatch.setattr(llm.settings, "llm_fallback_model", "backup-model")
    monkeypatch.setattr(llm.settings, "llm_max_retries", 1)

    assert await llm.chat("sys", "hi") == "backup reply"
    assert calls == [llm.settings.deepseek_model, "backup-model"]
