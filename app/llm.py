"""LLM 与 Embedding 客户端。

- chat：DeepSeek（走 openai SDK，OpenAI 兼容）
- embed：DashScope text-embedding-v3（1024 维；SDK 为同步，用 to_thread 包装）
"""

from __future__ import annotations

import asyncio
from typing import Any

import dashscope
import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.resilience import TransientError, call_resilient

EMBED_MODEL = "text-embedding-v3"
EMBED_DIM = 1024

_llm: AsyncOpenAI | None = None


def _llm_client() -> AsyncOpenAI:
    global _llm
    if _llm is None:
        _llm = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=httpx.Timeout(
                settings.llm_read_timeout,
                connect=settings.llm_connect_timeout,
            ),
        )
    return _llm


async def _chat_once(model: str, messages: list[dict], kwargs: dict) -> str:
    resp = await _llm_client().chat.completions.create(
        model=model, messages=messages, **kwargs
    )
    return resp.choices[0].message.content or ""


async def chat(
    system: str,
    user: str,
    *,
    response_format: str | None = None,
    temperature: float = 0.3,
) -> str:
    """调用对话模型，返回文本。response_format 传 "json_object" 时要求 JSON 输出。

    可靠性：超时 + 指数退避重试 + 熔断；主模型重试耗尽且配置了备用模型时切换一次。
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs: dict[str, Any] = {"temperature": temperature}
    if response_format:
        kwargs["response_format"] = {"type": response_format}

    async def _primary() -> str:
        return await _chat_once(settings.deepseek_model, messages, kwargs)

    try:
        return await call_resilient(
            "llm:primary",
            _primary,
            timeout=settings.llm_read_timeout,
            attempts=settings.llm_max_retries,
            failure_threshold=settings.breaker_failure_threshold,
            reset_timeout=settings.breaker_reset_timeout,
        )
    except Exception as primary_error:
        fallback = settings.llm_fallback_model.strip()
        if not fallback or fallback == settings.deepseek_model:
            raise

        async def _fallback() -> str:
            return await _chat_once(fallback, messages, kwargs)

        try:
            return await call_resilient(
                "llm:fallback",
                _fallback,
                timeout=settings.llm_read_timeout,
                attempts=settings.llm_max_retries,
                failure_threshold=settings.breaker_failure_threshold,
                reset_timeout=settings.breaker_reset_timeout,
            )
        except Exception as fallback_error:
            raise fallback_error from primary_error


def _embed_sync(texts: list[str]) -> list[list[float]]:
    resp = dashscope.TextEmbedding.call(
        model=EMBED_MODEL,
        input=texts,
        dimension=EMBED_DIM,
        api_key=settings.dashscope_api_key,
    )
    if resp.status_code != 200:
        msg = f"embedding 失败: {resp.code} {resp.message}"
        # 429 / 5xx 属瞬时错误，交给重试；其余（鉴权/参数）直接失败
        if resp.status_code == 429 or resp.status_code >= 500:
            raise TransientError(msg)
        raise RuntimeError(msg)
    embs = resp.output["embeddings"]
    embs.sort(key=lambda e: e["text_index"])
    return [e["embedding"] for e in embs]


async def embed(texts: list[str]) -> list[list[float]]:
    """文本向量化（批量），返回与输入同序的向量列表（带超时/重试/熔断）。"""
    if not texts:
        return []

    async def _call() -> list[list[float]]:
        return await asyncio.to_thread(_embed_sync, texts)

    return await call_resilient(
        "embedding:dashscope",
        _call,
        timeout=settings.embed_timeout,
        attempts=settings.llm_max_retries,
        failure_threshold=settings.breaker_failure_threshold,
        reset_timeout=settings.breaker_reset_timeout,
    )
