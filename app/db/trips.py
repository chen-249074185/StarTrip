"""行程落库：保存 / 列表 / 详情。"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from app.db.pg import fetch


async def save_trip(
    session_id: str,
    title: str,
    plan: dict,
    score: float | None,
) -> int:
    rows = await fetch(
        """
        INSERT INTO trips (session_id, title, plan_json, score)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (session_id, title, Jsonb(plan), score),
    )
    return int(rows[0]["id"])


async def list_trips(session_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = await fetch(
        """
        SELECT id, title, score, created_at,
               COALESCE(jsonb_array_length(plan_json->'days'), 0) AS days
        FROM trips
        WHERE session_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (session_id, limit),
    )
    return [
        {
            "id": int(row["id"]),
            "title": row["title"],
            "score": float(row["score"]) if row["score"] is not None else None,
            "days": int(row["days"] or 0),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


async def get_trip(trip_id: int, session_id: str) -> dict[str, Any] | None:
    rows = await fetch(
        """
        SELECT id, session_id, title, plan_json, score, created_at
        FROM trips
        WHERE id = %s AND session_id = %s
        """,
        (trip_id, session_id),
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "id": int(row["id"]),
        "title": row["title"],
        "session_id": row["session_id"],
        "trip_plan": row["plan_json"],
        "score": float(row["score"]) if row["score"] is not None else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
