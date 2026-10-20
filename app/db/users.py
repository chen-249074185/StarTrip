"""用户表访问层。"""

from __future__ import annotations

from typing import Any

from app.db.pg import execute, fetch


async def get_user_by_username(username: str) -> dict[str, Any] | None:
    rows = await fetch(
        "SELECT id, username, password_hash FROM users WHERE username = %s",
        (username.strip(),),
    )
    return rows[0] if rows else None


async def upsert_user(username: str, password_hash: str) -> None:
    """创建用户；同名则更新密码（便于脚本重置）。"""
    await execute(
        """
        INSERT INTO users (username, password_hash)
        VALUES (%s, %s)
        ON CONFLICT (username)
        DO UPDATE SET password_hash = EXCLUDED.password_hash
        """,
        (username.strip(), password_hash),
    )
