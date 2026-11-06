"""结果状态：ok / degraded / cancelled。"""

from __future__ import annotations

from app.main import result_status

PLAN = {"days": [{"date": "D1", "spots": [{"name": "外滩"}]}]}
OK_GROUNDING = {"applicable": True, "ratio": 0.0, "ungrounded": []}


def test_status_ok_when_plan_valid_and_grounded():
    assert result_status(PLAN, {"ok": True}, OK_GROUNDING, cancelled=False) == "ok"


def test_status_degraded_on_validation_or_grounding():
    assert (
        result_status(PLAN, {"ok": False}, OK_GROUNDING, cancelled=False)
        == "degraded"
    )
    bad = {"applicable": True, "ratio": 1.0, "ungrounded": ["迪士尼"]}
    assert result_status(PLAN, {"ok": True}, bad, cancelled=False) == "degraded"
    assert (
        result_status(
            PLAN,
            {"ok": True},
            {"applicable": False, "ratio": 0.0},
            cancelled=False,
        )
        == "degraded"
    )


def test_status_cancelled_and_chat():
    assert result_status(PLAN, None, None, cancelled=True) == "cancelled"
    assert result_status(None, None, None, cancelled=False) == "ok"
