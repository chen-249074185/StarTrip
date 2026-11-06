"""签名会话：签发 / 校验 / 篡改拒绝。"""

from __future__ import annotations

from app.config import settings
from app.session import new_session_id, sign_session, verify_session


def test_sign_and_verify_roundtrip(monkeypatch):
    monkeypatch.setattr(settings, "session_secret", "unit-test-secret")
    raw = new_session_id()
    token = sign_session(raw)
    assert token.startswith(raw + ".")
    assert verify_session(token) == raw


def test_tampered_session_rejected(monkeypatch):
    monkeypatch.setattr(settings, "session_secret", "unit-test-secret")
    token = sign_session("session-a")
    bad = token.replace("session-a", "session-b")
    assert verify_session(bad) is None
    assert verify_session("no-dot") is None
    assert verify_session("") is None
