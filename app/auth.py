"""JWT 鉴权：密码哈希 / token 签发校验 / 当前用户依赖 / session 隔离。

- 密码：stdlib scrypt（内存硬，无额外依赖），格式 `scrypt$n$r$p$salt$hash`
- token：HS256，`sub=user_id`，默认 2h 过期
- `AUTH_ENABLED=false` 时 `get_current_user` 返回 None，保持 demo 兼容
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings
from app.db.users import get_user_by_username

ALGORITHM = "HS256"
bearer = HTTPBearer(auto_error=False)

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_MAXMEM = 64 * 1024 * 1024


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
        maxmem=_SCRYPT_MAXMEM,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=_SCRYPT_MAXMEM,
        )
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str) -> str:
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET 未配置")
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    sub = payload.get("sub")
    if not sub:
        raise JWTError("token 缺少 sub")
    return str(sub)


async def authenticate_user(username: str, password: str) -> dict | None:
    user = await get_user_by_username(username)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return user


async def get_current_user(
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str | None:
    """鉴权开启时必须带有效 Bearer token；关闭时返回 None。"""
    if not settings.auth_enabled:
        return None
    if cred is None:
        raise HTTPException(
            401, "未登录", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        return decode_access_token(cred.credentials)
    except JWTError as e:
        raise HTTPException(
            401, "token 无效或已过期", headers={"WWW-Authenticate": "Bearer"}
        ) from e


def thread_id_for(user_id: str | None, session_id: str) -> str:
    """Checkpoint 隔离：开启鉴权后，不同用户即使 session_id 相同也互不可见。"""
    return f"{user_id}:{session_id}" if user_id else session_id
