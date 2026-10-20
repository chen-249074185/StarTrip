"""创建或重置用户（写入 users 表）。

用法：
    python -m scripts.create_user admin
    python -m scripts.create_user admin my-password
    docker compose exec -T app python -m scripts.create_user admin
"""

from __future__ import annotations

import argparse
import asyncio
import getpass

from app.auth import hash_password
from app.db.pg import close_pool, init_schema, open_pool
from app.db.users import upsert_user


async def main(username: str, password: str) -> None:
    if len(password) < 8:
        raise SystemExit("密码至少 8 位")
    open_pool()
    await init_schema()
    try:
        await upsert_user(username, hash_password(password))
        print(f"用户已创建/更新: {username}")
    finally:
        close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="创建或重置 StarTrip 用户")
    parser.add_argument("username")
    parser.add_argument("password", nargs="?", help="不填则交互输入")
    args = parser.parse_args()
    pwd = args.password or getpass.getpass("密码: ")
    asyncio.run(main(args.username, pwd))
