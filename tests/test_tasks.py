"""任务清单清洗：白名单 / 参数收敛 / 去重 / 上限。"""

from __future__ import annotations

from app.tasks import sanitize_args, sanitize_tasks


def test_sanitize_args_only_scalars_and_limits_length():
    args = sanitize_args(
        {
            "city": "上" * 800,
            "budget": 100,
            "nested": {"x": 1},
            "list": [1, 2],
            "none": None,
        }
    )
    assert len(args["city"]) == 500
    assert args["budget"] == 100
    assert "nested" not in args
    assert "list" not in args
    assert args["none"] is None


def test_sanitize_tasks_filters_unknown_dedupes_and_caps():
    tasks = [
        {"tool": "maps_weather", "args": {"city": "上海"}},
        {"tool": "maps_weather", "args": {"city": "上海"}},
        {"tool": "not_a_tool", "args": {}},
        {"tool": "maps_text_search", "args": {"city": "上海", "keywords": "景点"}},
        "bad",
    ]
    cleaned = sanitize_tasks(tasks, allowed_tools={"maps_weather", "maps_text_search"}, max_tasks=1)
    assert cleaned == [{"tool": "maps_weather", "args": {"city": "上海"}}]


def test_sanitize_tasks_rejects_non_list():
    assert sanitize_tasks(None) == []
    assert sanitize_tasks({"tool": "x"}) == []
