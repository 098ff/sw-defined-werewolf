"""Pre-game room lifecycle. GameMaster owns role assignment and phase changes."""

import os
import secrets
import string
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from starlette.exceptions import HTTPException

from common.state_store import (
    InMemoryStateStore,
    RedisStateStore,
    StateConflictError,
    StateStore,
)
from common.trace import get_service_trace


class PlayerRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=20)]


class LobbyError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def generate_room_code() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(4))


def create_app(
    store: StateStore | None = None,
    gamemaster_client: httpx.AsyncClient | None = None,
    gamemaster_url: str | None = None,
) -> FastAPI:
    """Allow isolated tests to inject storage and an HTTP mock without live services."""
    if store is None:
        backend = os.getenv("STATE_STORE_BACKEND", "redis")
        if backend == "in_memory":
            store = InMemoryStateStore()
        elif backend == "redis":
            store = RedisStateStore(os.getenv("REDIS_URL", "redis://localhost:6379"))
        else:
            raise ValueError("STATE_STORE_BACKEND must be redis or in_memory")

    gm_url = (gamemaster_url or os.getenv("GAMEMASTER_URL", "http://gamemaster:8000")).rstrip("/")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if gamemaster_client is not None:
            yield
        else:
            async with httpx.AsyncClient(timeout=5.0) as client:
                app.state.gamemaster_client = client
                yield

    app = FastAPI(title="Werewolf Lobby Service", lifespan=lifespan)
    app.state.gamemaster_client = gamemaster_client

    def response(request: Request, data=None, *, status=200, error=None, trace=None):
        body = {
            "ok": error is None,
            "request_id": request.state.request_id,
            "trace": [get_service_trace("lobby"), *(trace or [])],
        }
        body["error" if error is not None else "data"] = error if error is not None else data
        return JSONResponse(body, status_code=status)

    @app.middleware("http")
    async def request_identity(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or f"req-{secrets.token_hex(16)}"
        result = await call_next(request)
        result.headers["X-Request-ID"] = request.state.request_id
        return result

    @app.exception_handler(LobbyError)
    async def lobby_error(request: Request, exc: LobbyError):
        return response(request, status=exc.status, error={"code": exc.code, "message": exc.message})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return response(request, status=400, error={
            "code": "INVALID_REQUEST", "message": "Provide valid JSON with a name of 2–20 characters."
        })

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return response(request, status=exc.status_code, error={
            "code": "INVALID_REQUEST", "message": str(exc.detail)
        })

    @app.exception_handler(StateConflictError)
    async def state_conflict(request: Request, exc: StateConflictError):
        return response(request, status=409, error={
            "code": "STATE_CONFLICT", "message": "Concurrent room update; please retry."
        })

    async def storage_unavailable(request: Request, exc: Exception):
        return response(request, status=503, error={
            "code": "STATE_STORE_UNAVAILABLE", "message": "State storage is unavailable."
        })

    app.add_exception_handler(RedisConnectionError, storage_unavailable)
    app.add_exception_handler(RedisTimeoutError, storage_unavailable)

    async def require_room(room_id):
        room = await store.get_room(room_id)
        if room is None:
            raise LobbyError(404, "ROOM_NOT_FOUND", "Room not found.")
        return room

    async def authenticate(request: Request, room_id: str):
        authorization = request.headers.get("Authorization")
        if not authorization:
            raise LobbyError(401, "MISSING_TOKEN", "Bearer token required.")
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise LobbyError(401, "INVALID_TOKEN", "Invalid Bearer token.")
        session = await store.get_player_session(parts[1])
        if not session or session.get("room_id") != room_id:
            raise LobbyError(401, "INVALID_TOKEN", "Invalid session for this room.")
        room = await require_room(room_id)
        if session.get("player_id") not in room["players"]:
            raise LobbyError(401, "INVALID_TOKEN", "Player is no longer in this room.")
        return session["player_id"], room

    @app.get("/health/live")
    async def live(request: Request):
        return response(request, {"status": "UP", "service": "lobby"})

    @app.get("/health/ready")
    async def ready(request: Request):
        # A non-mutating read exercises connectivity through the shared interface.
        await store.get_room("__lobby_readiness__")
        return response(request, {"status": "UP", "service": "lobby"})

    @app.post("/api/lobby/rooms")
    async def create_room(payload: PlayerRequest, request: Request):
        player_id = f"p-{secrets.token_hex(16)}"
        token = secrets.token_urlsafe(32)
        for _ in range(10):
            room_id = generate_room_code()
            initial_state = {
                "room_id": room_id, "version": 1, "phase": "WAITING",
                "day_count": 0, "phase_end_time": None, "winner": None,
                "announcement": "Waiting for players to join...",
                "host_player_id": player_id,
                "players": {player_id: {
                    "player_id": player_id, "name": payload.name, "role": None,
                    "alive": True, "is_host": True,
                }},
                "night_actions": {
                    "wolf_votes": {}, "doctor_target": None, "seer_target": None,
                    "seer_result_by_player": {},
                },
                "day_votes": {},
            }
            if await store.create_room(room_id, initial_state):
                break
        else:
            raise LobbyError(503, "SERVICE_UNAVAILABLE", "Could not allocate a room code; please retry.")
        await store.create_player_session(token, {"room_id": room_id, "player_id": player_id})
        return response(request, {
            "room_id": room_id, "player_id": player_id,
            "player_token": token, "is_host": True,
        })

    @app.post("/api/lobby/rooms/{room_id}/join")
    async def join_room(room_id: str, payload: PlayerRequest, request: Request):
        await require_room(room_id)
        player_id = f"p-{secrets.token_hex(16)}"
        token = secrets.token_urlsafe(32)

        def add_player(state):
            # CAS can re-run this function: validate against the current state each time.
            if state["phase"] != "WAITING":
                raise LobbyError(409, "GAME_ALREADY_STARTED", "Room is already in progress.")
            if len(state["players"]) >= 6:
                raise LobbyError(409, "ROOM_FULL", "Room reached maximum capacity of 6 players.")
            if any(p["name"].casefold() == payload.name.casefold() for p in state["players"].values()):
                raise LobbyError(400, "INVALID_REQUEST", "Player name already in use.")
            state["players"][player_id] = {
                "player_id": player_id, "name": payload.name, "role": None,
                "alive": True, "is_host": False,
            }
            return state

        try:
            await store.update_room(room_id, add_player)
        except ValueError:
            # Room may expire between the initial read and the atomic mutation.
            raise LobbyError(404, "ROOM_NOT_FOUND", "Room not found.") from None
        await store.create_player_session(token, {"room_id": room_id, "player_id": player_id})
        return response(request, {
            "room_id": room_id, "player_id": player_id,
            "player_token": token, "is_host": False,
        })

    @app.get("/api/lobby/rooms/{room_id}")
    async def get_lobby_state(room_id: str, request: Request):
        _, room = await authenticate(request, room_id)
        return response(request, {
            "room_id": room_id, "phase": room["phase"],
            "host_player_id": room["host_player_id"],
            "players": [{k: p[k] for k in ("player_id", "name", "is_host")}
                        for p in room["players"].values()],
        })

    @app.post("/api/lobby/rooms/{room_id}/start")
    async def start_game(room_id: str, request: Request):
        player_id, room = await authenticate(request, room_id)
        if player_id != room["host_player_id"]:
            raise LobbyError(403, "HOST_ONLY", "Only room host can start the game.")
        if room["phase"] != "WAITING":
            raise LobbyError(409, "GAME_ALREADY_STARTED", "Room is already in progress.")
        count = len(room["players"])
        if count < 4:
            raise LobbyError(400, "INVALID_REQUEST", "At least 4 players required to start")
        if count > 6:
            raise LobbyError(400, "INVALID_REQUEST", "At most 6 players allowed to start")

        # Do not retry: a timeout can occur after GameMaster has committed initialization.
        # GameMaster must revalidate WAITING/player count atomically during initialization.
        try:
            upstream = await app.state.gamemaster_client.post(
                f"{gm_url}/internal/rooms/{room_id}/initialize",
                headers={"X-Request-ID": request.state.request_id},
            )
            body = upstream.json()
        except (httpx.RequestError, ValueError):
            raise LobbyError(503, "SERVICE_UNAVAILABLE", "GameMaster is unavailable.") from None
        if not isinstance(body, dict):
            raise LobbyError(503, "SERVICE_UNAVAILABLE", "Invalid GameMaster response.")
        trace = body.get("trace", [])
        if not isinstance(trace, list) or any(
            not isinstance(hop, dict) or any(not isinstance(hop.get(k), str) for k in ("service", "pod", "node"))
            for hop in trace
        ):
            trace = []
        if upstream.status_code == 200 and body.get("ok") is True:
            return response(request, {"status": "STARTED"}, trace=trace)
        error = body.get("error")
        if 400 <= upstream.status_code < 500 and isinstance(error, dict) and all(
            isinstance(error.get(k), str) for k in ("code", "message")
        ):
            return response(request, status=upstream.status_code,
                            error={k: error[k] for k in ("code", "message")}, trace=trace)
        raise LobbyError(503, "SERVICE_UNAVAILABLE", "GameMaster could not initialize the room.")

    return app


app = create_app()
