"""LLM 与 Embedding 客户端。

- chat：DeepSeek（走 openai SDK，OpenAI 兼容）
- embed：DashScope text-embedding-v3（1024 维；SDK 为同步，用 to_thread 包装）
"""

from __future__ import annotations

import asyncio
from typing import Any

import dashscope
from openai import AsyncOpenAI

from app.config import settings

EMBED_MODEL = "text-embedding-v3"
EMBED_DIM = 1024

_llm: AsyncOpenAI | None = None


def _llm_client() -> AsyncOpenAI:
    global _llm
    if _llm is None:
        _llm = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
    return _llm


async def chat(
    system: str,
    user: str,
    *,
    response_format: str | None = None,
    temperature: float = 0.3,
) -> str:
    """调用对话模型，返回文本。response_format 传 "json_object" 时要求 JSON 输出。"""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs: dict[str, Any] = {
        "model": settings.deepseek_model,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        kwargs["response_format"] = {"type": response_format}
    resp = await _llm_client().chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def _embed_sync(texts: list[str]) -> list[list[float]]:
    resp = dashscope.TextEmbedding.call(
        model=EMBED_MODEL,
        input=texts,
        dimension=EMBED_DIM,
        api_key=settings.dashscope_api_key,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"embedding 失败: {resp.code} {resp.message}")
    embs = resp.output["embeddings"]
    embs.sort(key=lambda e: e["text_index"])
    return [e["embedding"] for e in embs]


async def embed(texts: list[str]) -> list[list[float]]:
    """文本向量化（批量），返回与输入同序的向量列表。"""
    if not texts:
        return []
    return await asyncio.to_thread(_embed_sync, texts)
