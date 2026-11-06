"""接地检查与通勤估算：景点依据 / 未接地识别 / 坐标距离。"""

from __future__ import annotations

import json

from app.grounding import estimate_travel_times, extract_pois, ground_plan

TOOL_RESULTS = {
    "maps_text_search": [
        json.dumps(
            {
                "pois": [
                    {
                        "name": "外滩",
                        "address": "中山东一路",
                        "location": "121.490,31.240",
                        "type": "风景名胜",
                    },
                    {
                        "name": "豫园",
                        "address": "福佑路",
                        "location": "121.492,31.227",
                        "type": "风景名胜",
                    },
                ]
            },
            ensure_ascii=False,
        )
    ]
}


def _plan(*names: str) -> dict:
    return {
        "days": [
            {
                "date": "D1",
                "spots": [
                    {"name": name, "time": f"{9 + i:02d}:00-{10 + i:02d}:00"}
                    for i, name in enumerate(names)
                ],
            }
        ]
    }


def test_extract_pois_handles_nested_payloads():
    pois = extract_pois(TOOL_RESULTS)
    assert set(pois) == {"外滩", "豫园"}
    assert pois["外滩"]["location"] == (121.49, 31.24)


def test_ground_plan_marks_hallucinations():
    result = ground_plan(_plan("外滩", "迪士尼"), TOOL_RESULTS, [])
    assert result["applicable"] is True
    assert result["total"] == 2
    assert result["grounded"] == 1
    assert result["ungrounded"] == ["迪士尼"]
    assert result["ratio"] == 0.5


def test_ground_plan_uses_rag_text_and_is_not_applicable_without_evidence():
    rag = ["上海攻略：外滩夜景和豫园老城隍庙都值得去。"]
    result = ground_plan(_plan("外滩", "豫园"), {}, rag)
    assert result["applicable"] is True
    assert result["ratio"] == 0.0

    empty = ground_plan(_plan("外滩"), {}, [])
    assert empty["applicable"] is False
    assert empty["ratio"] == 0.0


def test_estimate_travel_times_from_coordinates():
    travel = estimate_travel_times(_plan("外滩", "豫园"), extract_pois(TOOL_RESULTS))
    minutes = travel[("外滩", "豫园")]
    assert 5 <= minutes <= 30
