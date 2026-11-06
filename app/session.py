"""可选签名的会话 ID。

`AUTH_ENABLED=false` 的公开 Demo 里，session_id 是唯一隔离手段；
如果允许客户端随便传，猜到别人的 id 就能读行程。开启
`REQUIRE_SIGNED_SESSION=true` 后，客户端先用 /api/session 换一个
`<随机串>.<HMAC>`，服务端校验签名后才使用。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from app.config import settings


def _secret() -> bytes:
    raw = settings.session_secret or settings.jwt_secret or "startrip-dev-only"
    return raw.encode("utf-8")


def new_session_id() -> str:
    return secrets.token_urlsafe(18)


def sign_session(session_id: str) -> str:
    signature = hmac.new(
        _secret(), str(session_id).encode("utf-8"), hashlib.sha256
    ).digest()
    return f"{session_id}.{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"


def verify_session(token: str) -> str | None:
    """校验签名，成功返回原始 session_id；失败返回 None。"""
    if not isinstance(token, str) or "." not in token:
        return None
    session_id, _, signature = token.rpartition(".")
    if not session_id or not signature:
        return None
    expected = hmac.new(
        _secret(), session_id.encode("utf-8"), hashlib.sha256
    ).digest()
    expected_text = base64.urlsafe_b64encode(expected).decode("ascii").rstrip("=")
    if not hmac.compare_digest(signature, expected_text):
        return None
    return session_id
