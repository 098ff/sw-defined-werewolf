import os
import random
import secrets
import string
import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from common.state_store import StateStore, InMemoryStateStore, RedisStateStore
from common.trace import get_service_trace

app = FastAPI(title="Werewolf Lobby Service")

STATE_STORE_BACKEND = os.getenv("STATE_STORE_BACKEND", "in_memory")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
GAMEMASTER_URL = os.getenv("GAMEMASTER_URL", "http://localhost:8002")

if STATE_STORE_BACKEND == "redis":
    store: StateStore = RedisStateStore(REDIS_URL)
else:
    store: StateStore = InMemoryStateStore()

http_client = httpx.AsyncClient(timeout=5.0)

class CreateRoomRequest(BaseModel):
    name: str

class JoinRoomRequest(BaseModel):
    name: str

def generate_room_code(length: int = 4) -> str:
    return "".join(secrets.choice(string.ascii_uppercase) for _ in range(length))

@app.on_event("shutdown")
async def shutdown():
    await http_client.aclose()

@app.get("/health/live")
@app.get("/health/ready")
async def health():
    return {
        "ok": True,
        "status": "UP",
        "service": "lobby",
        "trace": [get_service_trace("lobby")]
    }

@app.post("/api/lobby/rooms")
async def create_room(payload: CreateRoomRequest, x_request_id: str = Header("req-default", alias="X-Request-ID")):
    room_id = generate_room_code()
    player_id = f"p-{secrets.token_hex(4)}"
    token = secrets.token_urlsafe(32)

    initial_state = {
        "room_id": room_id,
        "phase": "WAITING",
        "day_count": 0,
        "phase_version": 1,
        "winner": None,
        "announcement": "Waiting for players to join...",
        "host_player_id": player_id,
        "players": {
            player_id: {
                "player_id": player_id,
                "name": payload.name.strip(),
                "role": None,
                "alive": True,
                "is_host": True
            }
        }
    }

    success = await store.create_room(room_id, initial_state)
    if not success:
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": {"code": "ROOM_EXISTS", "message": "Collision creating room"}, "request_id": x_request_id, "trace": [get_service_trace("lobby")]}
        )

    await store.create_player_session(token, {"room_id": room_id, "player_id": player_id, "is_host": True})

    return {
        "ok": True,
        "data": {
            "room_id": room_id,
            "player_id": player_id,
            "player_token": token,
            "is_host": True
        },
        "request_id": x_request_id,
        "trace": [get_service_trace("lobby")]
    }

@app.post("/api/lobby/rooms/{room_id}/join")
async def join_room(room_id: str, payload: JoinRoomRequest, x_request_id: str = Header("req-default", alias="X-Request-ID")):
    room = await store.get_room(room_id)
    if not room:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": {"code": "ROOM_NOT_FOUND", "message": f"Room {room_id} not found"}, "request_id": x_request_id, "trace": [get_service_trace("lobby")]}
        )

    if room.get("phase") != "WAITING":
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": {"code": "GAME_ALREADY_STARTED", "message": "Room is already in progress"}, "request_id": x_request_id, "trace": [get_service_trace("lobby")]}
        )

    players = room.get("players", {})
    if len(players) >= 6:
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": {"code": "ROOM_FULL", "message": "Room reached maximum capacity of 6 players"}, "request_id": x_request_id, "trace": [get_service_trace("lobby")]}
        )

    clean_name = payload.name.strip()
    if any(p.get("name", "").lower() == clean_name.lower() for p in players.values()):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": {"code": "DUPLICATE_NAME", "message": "Player name already in use"}, "request_id": x_request_id, "trace": [get_service_trace("lobby")]}
        )

    player_id = f"p-{secrets.token_hex(4)}"
    token = secrets.token_urlsafe(32)

    def add_player(state):
        state["players"][player_id] = {
            "player_id": player_id,
            "name": clean_name,
            "role": None,
            "alive": True,
            "is_host": False
        }
        return state

    await store.update_room(room_id, add_player)
    await store.create_player_session(token, {"room_id": room_id, "player_id": player_id, "is_host": False})

    return {
        "ok": True,
        "data": {
            "room_id": room_id,
            "player_id": player_id,
            "player_token": token,
            "is_host": False
        },
        "request_id": x_request_id,
        "trace": [get_service_trace("lobby")]
    }

@app.get("/api/lobby/rooms/{room_id}")
async def get_lobby_state(room_id: str, x_request_id: str = Header("req-default", alias="X-Request-ID")):
    room = await store.get_room(room_id)
    if not room:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": {"code": "ROOM_NOT_FOUND", "message": "Room not found"}, "request_id": x_request_id, "trace": [get_service_trace("lobby")]}
        )

    players = [
        {"player_id": p["player_id"], "name": p["name"], "is_host": p.get("is_host", False)}
        for p in room.get("players", {}).values()
    ]

    return {
        "ok": True,
        "data": {
            "room_id": room_id,
            "phase": room.get("phase", "WAITING"),
            "host_player_id": room.get("host_player_id"),
            "players": players
        },
        "request_id": x_request_id,
        "trace": [get_service_trace("lobby")]
    }

@app.post("/api/lobby/rooms/{room_id}/start")
async def start_game(
    room_id: str,
    authorization: str = Header(None),
    x_request_id: str = Header("req-default", alias="X-Request-ID")
):
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": {"code": "UNAUTHORIZED", "message": "Missing Bearer token"}, "request_id": x_request_id, "trace": [get_service_trace("lobby")]}
        )

    token = authorization.split("Bearer ")[1].strip()
    session = await store.get_player_session(token)
    if not session or session.get("room_id") != room_id or not session.get("is_host"):
        return JSONResponse(
            status_code=403,
            content={"ok": False, "error": {"code": "HOST_ONLY", "message": "Only room host can start the game"}, "request_id": x_request_id, "trace": [get_service_trace("lobby")]}
        )

    room = await store.get_room(room_id)
    if not room:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": {"code": "ROOM_NOT_FOUND", "message": "Room not found"}, "request_id": x_request_id, "trace": [get_service_trace("lobby")]}
        )

    player_count = len(room.get("players", {}))
    if player_count < 4 or player_count > 6:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": {"code": "INVALID_PLAYER_COUNT", "message": "Game requires 4 to 6 players to start"}, "request_id": x_request_id, "trace": [get_service_trace("lobby")]}
        )

    # Call GameMaster internal endpoint
    try:
        gm_resp = await http_client.post(
            f"{GAMEMASTER_URL}/internal/rooms/{room_id}/initialize",
            headers={"X-Request-ID": x_request_id}
        )
        if gm_resp.status_code != 200:
            return JSONResponse(
                status_code=gm_resp.status_code,
                content=gm_resp.json()
            )
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": {"code": "GAMEMASTER_UNAVAILABLE", "message": str(exc)}, "request_id": x_request_id, "trace": [get_service_trace("lobby")]}
        )

    return {
        "ok": True,
        "data": {"status": "STARTED", "room_id": room_id},
        "request_id": x_request_id,
        "trace": [get_service_trace("lobby")]
    }
