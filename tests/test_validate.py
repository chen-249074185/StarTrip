"""确定性行程校验：时间/预算/重复/约束/天数。"""

from __future__ import annotations

from app.validate import extract_constraints, validate_plan


def _plan() -> dict:
    return {
        "days": [
            {
                "date": "D1",
                "budget_total": 100,
                "spots": [
                    {"name": "外滩", "time": "09:00-10:30", "budget": 0},
                    {"name": "豫园", "time": "10:45-12:00", "budget": 40},
                ],
            }
        ]
    }


def test_valid_plan_passes():
    result = validate_plan(_plan(), user_input="上海一日游，预算 500", must_include=["外滩"])
    assert result.ok
    assert result.checks["time"] is True
    assert result.checks["budget"] is True
    assert result.metrics["spots"] == 2


def test_time_overlap_fails():
    plan = _plan()
    plan["days"][0]["spots"][1]["time"] = "10:00-11:00"
    result = validate_plan(plan)
    assert not result.ok
    assert result.checks["time"] is False
    assert any("重叠" in e for e in result.errors)


def test_budget_overrun_fails():
    result = validate_plan(_plan(), user_input="上海一日游，预算 50")
    assert not result.ok
    assert result.checks["budget"] is False
    assert any("预算超支" in e for e in result.errors)


def test_duplicate_and_missing_required_fail():
    plan = _plan()
    plan["days"][0]["spots"].append({"name": "外滩", "time": "13:00-14:00", "budget": 0})
    result = validate_plan(plan, must_include=["外滩", "迪士尼"])
    assert not result.ok
    assert result.checks["duplicates"] is False
    assert result.checks["must_include"] is False


def test_must_avoid_fails():
    result = validate_plan(_plan(), must_avoid=["豫园"])
    assert not result.ok
    assert result.checks["must_avoid"] is False


def test_travel_time_gap_fails():
    plan = _plan()
    result = validate_plan(plan, travel_times={("外滩", "豫园"): 30})
    assert not result.ok
    assert any("路程" in e for e in result.errors)


def test_extract_constraints_cn_days_and_budget():
    constraints = extract_constraints("上海两日游，预算 1000，想少走路")
    assert constraints["days"] == 2
    assert constraints["budget"] == 1000


def test_extract_constraints_wan_and_two_digit_cn_days():
    assert extract_constraints("北京 1.5 万预算玩三天")["budget"] == 15000
    assert extract_constraints("北京 1.5 万预算玩三天")["days"] == 3
    assert extract_constraints("西安十一日游")["days"] == 11
    assert extract_constraints("上海二十日游")["days"] == 20


def test_time_range_accepts_tilde():
    plan = _plan()
    plan["days"][0]["spots"][0]["time"] = "09:00~10:30"
    result = validate_plan(plan)
    assert result.checks["time"] is True


def test_missing_time_only_warns():
    plan = {"days": [{"date": "D1", "spots": [{"name": "外滩"}]}]}
    result = validate_plan(plan)
    assert result.ok
    assert result.metrics["missing_time"] == 1
    assert result.warnings
