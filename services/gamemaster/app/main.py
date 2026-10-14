import os
import random
import time
from typing import Dict, List, Optional
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from common.state_store import StateStore, InMemoryStateStore, RedisStateStore
from common.trace import get_service_trace

app = FastAPI(title="Werewolf GameMaster Service")

STATE_STORE_BACKEND = os.getenv("STATE_STORE_BACKEND", "in_memory")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

if STATE_STORE_BACKEND == "redis":
    store: StateStore = RedisStateStore(REDIS_URL)
else:
    store: StateStore = InMemoryStateStore()

ROLE_CONFIGS = {
    4: ["WEREWOLF", "DOCTOR", "SEER", "VILLAGER"],
    5: ["WEREWOLF", "DOCTOR", "SEER", "VILLAGER", "VILLAGER"],
    6: ["WEREWOLF", "WEREWOLF", "DOCTOR", "SEER", "VILLAGER", "VILLAGER"]
}

class NightActionRequest(BaseModel):
    phase_version: int
    action: str
    target_id: str

class VoteRequest(BaseModel):
    phase_version: int
    target_id: str

@app.get("/health/live")
@app.get("/health/ready")
async def health():
    return {
        "ok": True,
        "status": "UP",
        "service": "gamemaster",
        "trace": [get_service_trace("gamemaster")]
    }

@app.post("/internal/rooms/{room_id}/initialize")
async def initialize_game(room_id: str, x_request_id: str = Header("req-default", alias="X-Request-ID")):
    room = await store.get_room(room_id)
    if not room:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": {"code": "ROOM_NOT_FOUND", "message": "Room not found"}, "request_id": x_request_id, "trace": [get_service_trace("gamemaster")]}
        )

    players = room.get("players", {})
    count = len(players)
    if count not in ROLE_CONFIGS:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": {"code": "INVALID_PLAYER_COUNT", "message": f"Requires 4-6 players, got {count}"}, "request_id": x_request_id, "trace": [get_service_trace("gamemaster")]}
        )

    roles = ROLE_CONFIGS[count].copy()
    random.shuffle(roles)

    def init_mutator(state):
        player_keys = list(state["players"].keys())
        for idx, pkey in enumerate(player_keys):
            state["players"][pkey]["role"] = roles[idx]
            state["players"][pkey]["alive"] = True

        state["phase"] = "NIGHT"
        state["day_count"] = 1
        state["phase_version"] = 1
        state["phase_end_time"] = int(time.time()) + 45
        state["announcement"] = "Night 1 has fallen over the village. Villagers sleep."
        state["night_actions"] = {
            "wolf_votes": {},
            "doctor_target": None,
            "seer_target": None,
            "seer_result_by_player": {}
        }
        state["day_votes"] = {}
        return state

    updated = await store.update_room(room_id, init_mutator)

    return {
        "ok": True,
        "data": {"status": "INITIALIZED", "room_id": room_id},
        "request_id": x_request_id,
        "trace": [get_service_trace("gamemaster")]
    }

@app.get("/api/game/rooms/{room_id}/state")
async def get_state(
    room_id: str,
    authorization: str = Header(None),
    x_request_id: str = Header("req-default", alias="X-Request-ID")
):
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": {"code": "UNAUTHORIZED", "message": "Missing Bearer token"}, "request_id": x_request_id, "trace": [get_service_trace("gamemaster")]}
        )

    token = authorization.split("Bearer ")[1].strip()
    session = await store.get_player_session(token)
    if not session or session.get("room_id") != room_id:
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": {"code": "INVALID_SESSION", "message": "Session not found for token"}, "request_id": x_request_id, "trace": [get_service_trace("gamemaster")]}
        )

    caller_id = session.get("player_id")
    room = await store.get_room(room_id)
    if not room:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": {"code": "ROOM_NOT_FOUND", "message": "Room not found"}, "request_id": x_request_id, "trace": [get_service_trace("gamemaster")]}
        )

    players = room.get("players", {})
    caller_player = players.get(caller_id, {})
    caller_role = caller_player.get("role")
    game_ended = (room.get("phase") == "ENDED")

    # Sanitize player list
    sanitized_players = []
    for pid, pdata in players.items():
        is_me = (pid == caller_id)
        is_fellow_wolf = (caller_role == "WEREWOLF" and pdata.get("role") == "WEREWOLF")
        visible_role = pdata.get("role") if (is_me or is_fellow_wolf or game_ended) else None

        sanitized_players.append({
            "player_id": pid,
            "name": pdata["name"],
            "role": visible_role,
            "alive": pdata.get("alive", True),
            "is_host": pdata.get("is_host", False)
        })

    # Prepare private info for caller
    private_info = {}
    if caller_role == "SEER":
        seer_res = room.get("night_actions", {}).get("seer_result_by_player", {}).get(caller_id)
        if seer_res:
            private_info["seer_result"] = seer_res

    player_view = {
        "room_id": room_id,
        "phase": room.get("phase"),
        "day_count": room.get("day_count", 1),
        "phase_version": room.get("phase_version", 1),
        "phase_end_time": room.get("phase_end_time", 0),
        "winner": room.get("winner"),
        "announcement": room.get("announcement", ""),
        "me": {
            "player_id": caller_id,
            "name": caller_player.get("name", "Unknown"),
            "role": caller_role,
            "alive": caller_player.get("alive", True),
            "private_info": private_info
        },
        "players": sanitized_players
    }

    return {
        "ok": True,
        "data": player_view,
        "request_id": x_request_id,
        "trace": [get_service_trace("gamemaster")]
    }

@app.post("/api/game/rooms/{room_id}/night-actions")
async def submit_night_action(
    room_id: str,
    payload: NightActionRequest,
    authorization: str = Header(None),
    x_request_id: str = Header("req-default", alias="X-Request-ID")
):
    token = authorization.split("Bearer ")[1].strip() if authorization else ""
    session = await store.get_player_session(token)
    if not session or session.get("room_id") != room_id:
        return JSONResponse(status_code=401, content={"ok": False, "error": {"code": "UNAUTHORIZED", "message": "Invalid session"}, "request_id": x_request_id, "trace": [get_service_trace("gamemaster")]})

    return {
        "ok": True,
        "data": {"status": "ACCEPTED", "action": payload.action, "target_id": payload.target_id},
        "request_id": x_request_id,
        "trace": [get_service_trace("gamemaster")]
    }

@app.post("/api/game/rooms/{room_id}/vote")
async def submit_vote(
    room_id: str,
    payload: VoteRequest,
    authorization: str = Header(None),
    x_request_id: str = Header("req-default", alias="X-Request-ID")
):
    token = authorization.split("Bearer ")[1].strip() if authorization else ""
    session = await store.get_player_session(token)
    if not session or session.get("room_id") != room_id:
        return JSONResponse(status_code=401, content={"ok": False, "error": {"code": "UNAUTHORIZED", "message": "Invalid session"}, "request_id": x_request_id, "trace": [get_service_trace("gamemaster")]})

    return {
        "ok": True,
        "data": {"status": "VOTE_CAST", "target_id": payload.target_id},
        "request_id": x_request_id,
        "trace": [get_service_trace("gamemaster")]
    }
