"""保底回复节点：与旅行无关的普通对话，直接让 LLM 自然回复。"""

from __future__ import annotations

from app.llm import chat
from app.memory import prior_history
from app.state import TripState

CHAT_PROMPT = (
    "你是 StarTrip 旅行助手。用户可能问与旅行无关的问题，请友好、简洁地回应；"
    "如果话题能自然引到旅行，可以顺势问一下目的地 / 天数 / 预算。"
)


async def chat_reply(state: TripState) -> dict:
    user_input = state.get("user_input", "")
    prior = prior_history(state.get("history") or [])
    msg = f"最近对话:\n{prior}\n\n用户:{user_input}" if prior else user_input
    try:
        reply = await chat(CHAT_PROMPT, msg, temperature=0.7)
    except Exception:  # noqa: BLE001
        reply = "我在～想聊旅行还是别的？说说你的需求吧。"
    return {"reply": reply, "options": []}
