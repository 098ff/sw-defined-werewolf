"""GameMaster Service Application package."""
import os
import time
import uuid
from typing import Any, Callable, Dict, Optional, Tuple

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from common.state_store import StateStore, StateConflictError, InMemoryStateStore, RedisStateStore
from common.trace import get_service_trace

from . import engine
from .engine import GameError

app = FastAPI(title="Werewolf GameMaster Service")

STATE_STORE_BACKEND = os.getenv("STATE_STORE_BACKEND", "in_memory")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"
DEMO_SECRET = os.getenv("DEMO_SECRET", "")

if STATE_STORE_BACKEND == "redis":
    store: StateStore = RedisStateStore(REDIS_URL)
else:
    store: StateStore = InMemoryStateStore()


class NightActionRequest(BaseModel):
    phase_version: int
    action: str
    target_id: str


class VoteRequest(BaseModel):
    phase_version: int
    target_id: str


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------

def _request_id(value: Optional[str]) -> str:
    return value or f"req-{uuid.uuid4().hex[:8]}"


def ok(data: Any, request_id: str) -> Dict[str, Any]:
    return {"ok": True, "data": data, "request_id": request_id, "trace": [get_service_trace("gamemaster")]}


def fail(status: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "ok": False,
            "error": {"code": code, "message": message},
            "request_id": request_id,
            "trace": [get_service_trace("gamemaster")],
        },
    )


@app.exception_handler(GameError)
async def game_error_handler(request: Request, exc: GameError):
    return fail(exc.status, exc.code, exc.message, _request_id(request.headers.get("X-Request-ID")))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return fail(400, "INVALID_REQUEST", "Malformed request body", _request_id(request.headers.get("X-Request-ID")))


@app.exception_handler(StateConflictError)
async def conflict_error_handler(request: Request, exc: StateConflictError):
    # Mapping defined in docs/roles/05-role-chat-statestore-qa.md section 2.1
    return fail(409, "STATE_CONFLICT", "Concurrent update, please retry", _request_id(request.headers.get("X-Request-ID")))


@app.exception_handler(Exception)
async def store_error_handler(request: Request, exc: Exception):
    # Redis connection errors surface here; anything else is still reported in the envelope
    code = "STATE_STORE_UNAVAILABLE" if "redis" in type(exc).__module__ else "INTERNAL_ERROR"
    status = 503 if code == "STATE_STORE_UNAVAILABLE" else 500
    return fail(status, code, str(exc) or type(exc).__name__, _request_id(request.headers.get("X-Request-ID")))


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

async def server_now() -> int:
    """Authoritative clock: Redis TIME so every pod agrees, local clock when running in-memory."""
    if isinstance(store, RedisStateStore):
        try:
            r = await store._get_redis()
            seconds, _ = await r.time()
            return int(seconds)
        except Exception:
            pass
    return int(time.time())


async def authenticate(room_id: str, authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise GameError(401, "MISSING_TOKEN", "Missing Bearer token")
    token = authorization[len("Bearer "):].strip()
    session = await store.get_player_session(token)
    if not session or session.get("room_id") != room_id:
        raise GameError(401, "INVALID_TOKEN", "Session not found for token")
    return session["player_id"]


async def mutate_room(room_id: str, mutator: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
    """Runs a rule-engine mutator atomically (Redis CAS) so concurrent pods never double-advance a phase."""
    if await store.get_room(room_id) is None:
        raise GameError(404, "ROOM_NOT_FOUND", "Room not found")
    return await store.update_room(room_id, mutator)


async def load_current_room(room_id: str) -> Tuple[Dict[str, Any], int]:
    """Returns the room after applying advance_if_expired() against the server clock."""
    room = await store.get_room(room_id)
    if room is None:
        raise GameError(404, "ROOM_NOT_FOUND", "Room not found")
    now = await server_now()
    if engine.is_expired(room, now):
        # Re-check inside the mutator: another pod may have advanced it first
        room = await store.update_room(room_id, lambda s: (engine.advance_if_expired(s, now), s)[1])
    return room, now


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health/live")
async def health_live():
    return {"ok": True, "status": "UP", "service": "gamemaster", "trace": [get_service_trace("gamemaster")]}


@app.get("/health/ready")
async def health_ready():
    try:
        await store.get_room("__health__")
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "status": "DOWN", "service": "gamemaster", "error": str(exc),
                     "trace": [get_service_trace("gamemaster")]},
        )
    return {"ok": True, "status": "UP", "service": "gamemaster", "trace": [get_service_trace("gamemaster")]}


@app.post("/internal/rooms/{room_id}/initialize")
async def initialize_game(room_id: str, x_request_id: Optional[str] = Header(None, alias="X-Request-ID")):
    rid = _request_id(x_request_id)
    now = await server_now()
    room = await mutate_room(room_id, lambda s: engine.initialize_game(s, now))
    return ok({"status": "INITIALIZED", "room_id": room_id, "phase": room["phase"],
               "phase_version": room["phase_version"]}, rid)


@app.get("/api/game/rooms/{room_id}/state")
async def get_state(
    room_id: str,
    authorization: Optional[str] = Header(None),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
):
    rid = _request_id(x_request_id)
    caller_id = await authenticate(room_id, authorization)
    room, now = await load_current_room(room_id)
    return ok(engine.build_player_view(room, caller_id, now), rid)


@app.post("/api/game/rooms/{room_id}/night-actions")
async def submit_night_action(
    room_id: str,
    payload: NightActionRequest,
    authorization: Optional[str] = Header(None),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
):
    rid = _request_id(x_request_id)
    caller_id = await authenticate(room_id, authorization)
    now = await server_now()

    def mutator(state: Dict[str, Any]) -> Dict[str, Any]:
        engine.advance_if_expired(state, now)
        return engine.submit_night_action(state, caller_id, payload.action, payload.target_id,
                                          payload.phase_version, now)

    await mutate_room(room_id, mutator)
    return ok({"status": "ACCEPTED", "action": payload.action, "target_id": payload.target_id}, rid)


@app.post("/api/game/rooms/{room_id}/vote")
async def submit_vote(
    room_id: str,
    payload: VoteRequest,
    authorization: Optional[str] = Header(None),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
):
    rid = _request_id(x_request_id)
    caller_id = await authenticate(room_id, authorization)
    now = await server_now()

    def mutator(state: Dict[str, Any]) -> Dict[str, Any]:
        engine.advance_if_expired(state, now)
        return engine.submit_vote(state, caller_id, payload.target_id, payload.phase_version)

    await mutate_room(room_id, mutator)
    return ok({"status": "VOTE_CAST", "target_id": payload.target_id}, rid)


@app.post("/api/demo/rooms/{room_id}/force-next")
async def force_next(
    room_id: str,
    x_demo_secret: Optional[str] = Header(None, alias="X-Demo-Secret"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
):
    rid = _request_id(x_request_id)
    if not DEMO_MODE or not DEMO_SECRET or x_demo_secret != DEMO_SECRET:
        raise GameError(403, "FORBIDDEN", "Demo mode disabled or wrong X-Demo-Secret")
    now = await server_now()
    room = await mutate_room(room_id, lambda s: engine.advance_phase(s, now))
    return ok({"status": "ADVANCED", "phase": room["phase"], "phase_version": room["phase_version"],
               "announcement": room.get("announcement", "")}, rid)
