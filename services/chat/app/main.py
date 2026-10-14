import os
import time
from typing import Dict, List, Optional
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from common.state_store import StateStore, InMemoryStateStore, RedisStateStore
from common.trace import get_service_trace

app = FastAPI(title="Werewolf Chat Service")

STATE_STORE_BACKEND = os.getenv("STATE_STORE_BACKEND", "in_memory")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

if STATE_STORE_BACKEND == "redis":
    store: StateStore = RedisStateStore(REDIS_URL)
else:
    store: StateStore = InMemoryStateStore()

class SendMessageRequest(BaseModel):
    channel: str = Field(..., regex="^(PUBLIC|WOLF|DEAD)$")
    text: str = Field(..., min_length=1, max_length=500)

@app.get("/health/live")
@app.get("/health/ready")
async def health():
    return {
        "ok": True,
        "status": "UP",
        "service": "chat",
        "trace": [get_service_trace("chat")]
    }

@app.get("/api/chat/rooms/{room_id}/messages")
async def get_messages(
    room_id: str,
    after_id: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    authorization: str = Header(None),
    x_request_id: str = Header("req-default", alias="X-Request-ID")
):
    token = authorization.split("Bearer ")[1].strip() if authorization and authorization.startswith("Bearer ") else ""
    session = await store.get_player_session(token)
    if not session or session.get("room_id") != room_id:
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": {"code": "UNAUTHORIZED", "message": "Invalid player session"}, "request_id": x_request_id, "trace": [get_service_trace("chat")]}
        )

    caller_id = session.get("player_id")
    room = await store.get_room(room_id)
    caller_player = room.get("players", {}).get(caller_id, {}) if room else {}
    caller_role = caller_player.get("role")
    is_alive = caller_player.get("alive", True)

    raw_messages = await store.get_chat(room_id, after_id=after_id, limit=limit)

    # Filter messages based on caller permissions
    filtered = []
    for msg in raw_messages:
        ch = msg.get("channel")
        if ch == "PUBLIC":
            filtered.append(msg)
        elif ch == "WOLF" and caller_role == "WEREWOLF":
            filtered.append(msg)
        elif ch == "DEAD" and not is_alive:
            filtered.append(msg)

    return {
        "ok": True,
        "data": {"messages": filtered},
        "request_id": x_request_id,
        "trace": [get_service_trace("chat")]
    }

@app.post("/api/chat/rooms/{room_id}/messages")
async def send_message(
    room_id: str,
    payload: SendMessageRequest,
    authorization: str = Header(None),
    x_request_id: str = Header("req-default", alias="X-Request-ID")
):
    token = authorization.split("Bearer ")[1].strip() if authorization and authorization.startswith("Bearer ") else ""
    session = await store.get_player_session(token)
    if not session or session.get("room_id") != room_id:
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": {"code": "UNAUTHORIZED", "message": "Invalid player session"}, "request_id": x_request_id, "trace": [get_service_trace("chat")]}
        )

    caller_id = session.get("player_id")
    room = await store.get_room(room_id)
    if not room:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": {"code": "ROOM_NOT_FOUND", "message": "Room not found"}, "request_id": x_request_id, "trace": [get_service_trace("chat")]}
        )

    caller_player = room.get("players", {}).get(caller_id, {})
    caller_name = caller_player.get("name", "Unknown")
    caller_role = caller_player.get("role")
    is_alive = caller_player.get("alive", True)
    phase = room.get("phase")

    # Channel Authorization Rules
    if payload.channel == "PUBLIC":
        if not is_alive or phase != "DAY":
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": {"code": "FORBIDDEN_CHANNEL", "message": "Only living players can post in PUBLIC chat during DAY"}, "request_id": x_request_id, "trace": [get_service_trace("chat")]}
            )
    elif payload.channel == "WOLF":
        if not is_alive or caller_role != "WEREWOLF" or phase != "NIGHT":
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": {"code": "FORBIDDEN_CHANNEL", "message": "Only living werewolves can post in WOLF chat during NIGHT"}, "request_id": x_request_id, "trace": [get_service_trace("chat")]}
            )
    elif payload.channel == "DEAD":
        if is_alive:
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": {"code": "FORBIDDEN_CHANNEL", "message": "Only dead players can post in DEAD chat"}, "request_id": x_request_id, "trace": [get_service_trace("chat")]}
            )

    msg_obj = {
        "channel": payload.channel,
        "sender_id": caller_id,
        "sender_name": caller_name,
        "text": payload.text.strip(),
        "created_at": int(time.time())
    }

    stored_msg = await store.append_chat(room_id, msg_obj)

    return {
        "ok": True,
        "data": stored_msg,
        "request_id": x_request_id,
        "trace": [get_service_trace("chat")]
    }
