"""PostgreSQL 访问层（pgvector）。

Windows 说明：psycopg 异步连接不能在 ProactorEventLoop（Windows 默认）下运行，
而 MCP 的 stdio 子进程又需要 Proactor loop。为兼顾两者，这里用**同步连接池 +
asyncio.to_thread** 包装（DB 为 I/O，线程执行开销可接受）。
"""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

_pool: ConnectionPool | None = None

# 知识库表 DDL（后续可迁到 Alembic）
DOCS_DDL = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS docs (
      id         BIGSERIAL PRIMARY KEY,
      title      TEXT,
      content    TEXT,
      source     TEXT,
      embedding  VECTOR(1024)
    )
    """,
    "CREATE INDEX IF NOT EXISTS docs_embedding_hnsw ON docs USING hnsw (embedding vector_cosine_ops)",
]

# 用户表（JWT 鉴权）
USERS_DDL = [
    """
    CREATE TABLE IF NOT EXISTS users (
      id            BIGSERIAL PRIMARY KEY,
      username      TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      created_at    TIMESTAMPTZ DEFAULT now()
    )
    """,
]

# 行程表
TRIPS_DDL = [
    """
    CREATE TABLE IF NOT EXISTS trips (
      id              BIGSERIAL PRIMARY KEY,
      session_id      TEXT NOT NULL,
      title           TEXT,
      plan_json       JSONB NOT NULL,
      score           NUMERIC(5,2),
      status          TEXT DEFAULT 'ok',
      validation_json JSONB,
      grounding_json  JSONB,
      created_at      TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS trips_session_created ON trips (session_id, created_at DESC)",
]

# 已有库的增量迁移（CREATE TABLE IF NOT EXISTS 不会补列）
TRIPS_MIGRATIONS = [
    "ALTER TABLE trips ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'ok'",
    "ALTER TABLE trips ADD COLUMN IF NOT EXISTS validation_json JSONB",
    "ALTER TABLE trips ADD COLUMN IF NOT EXISTS grounding_json JSONB",
]


def get_pool() -> ConnectionPool:
    """惰性创建同步连接池。"""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=10,
            timeout=settings.db_pool_timeout,
            open=False,
            configure=register_vector,          # 每连接注册 pgvector 类型
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
    return _pool


def open_pool() -> None:
    pool = get_pool()
    # 全新数据库里 vector 扩展还不存在，configure=register_vector 会在建连时
    # 报 "vector type not found"，导致连接池初始化失败。先用裸连接建扩展，
    # 再打开连接池。
    _ensure_vector_extension()
    pool.open()
    pool.wait(timeout=settings.db_pool_timeout)


def _ensure_vector_extension() -> None:
    with psycopg.connect(
        settings.database_url,
        autocommit=True,
        connect_timeout=max(1, int(settings.db_pool_timeout)),
    ) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _init_schema_sync() -> None:
    with get_pool().connection() as conn:
        for stmt in [*DOCS_DDL, *USERS_DDL, *TRIPS_DDL, *TRIPS_MIGRATIONS]:
            conn.execute(stmt)


async def init_schema() -> None:
    """建扩展与 docs 表（幂等）。"""
    await asyncio.to_thread(_init_schema_sync)


def _fetch_sync(query: str, params: tuple) -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        cur = conn.execute(query, params)
        return cur.fetchall()


async def fetch(query: str, params: tuple = ()) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_fetch_sync, query, params)


def _execute_sync(query: str, params: tuple) -> None:
    with get_pool().connection() as conn:
        conn.execute(query, params)


async def execute(query: str, params: tuple = ()) -> None:
    await asyncio.to_thread(_execute_sync, query, params)


def _execute_many_sync(query: str, params_list: list[tuple]) -> None:
    with (
        get_pool().connection() as conn,
        conn.transaction(),
        conn.cursor() as cur,
    ):
        cur.executemany(query, params_list)


async def execute_many(query: str, params_list: list[tuple]) -> None:
    """批量写入（单事务 executemany）；用于知识库构建，避免逐条往返。"""
    if not params_list:
        return
    await asyncio.to_thread(_execute_many_sync, query, params_list)
