import os
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from common.state_store import CHAT_HISTORY_LIMIT, StateStore, InMemoryStateStore, RedisStateStore
from common.trace import get_service_trace

app = FastAPI(title="Werewolf Chat Service")

STATE_STORE_BACKEND = os.getenv("STATE_STORE_BACKEND", "in_memory")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

if STATE_STORE_BACKEND == "redis":
    store: StateStore = RedisStateStore(REDIS_URL)
else:
    store: StateStore = InMemoryStateStore()


class ChatError(Exception):
    """Rule violation that maps directly onto the standard error envelope."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class SendMessageRequest(BaseModel):
    channel: str = Field(..., pattern="^(PUBLIC|WOLF|DEAD)$")
    text: str

    @field_validator("text")
    @classmethod
    def trimmed_length(cls, value: str) -> str:
        # Length is checked after trimming so whitespace-only messages are rejected
        value = value.strip()
        if not 1 <= len(value) <= 500:
            raise ValueError("text must be 1-500 characters after trimming")
        return value


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------

def _request_id(value: Optional[str]) -> str:
    return value or f"req-{uuid.uuid4().hex[:8]}"


def ok(data: Any, request_id: str) -> Dict[str, Any]:
    return {"ok": True, "data": data, "request_id": request_id, "trace": [get_service_trace("chat")]}


def fail(status: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "ok": False,
            "error": {"code": code, "message": message},
            "request_id": request_id,
            "trace": [get_service_trace("chat")],
        },
    )


@app.exception_handler(ChatError)
async def chat_error_handler(request: Request, exc: ChatError):
    return fail(exc.status, exc.code, exc.message, _request_id(request.headers.get("X-Request-ID")))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return fail(400, "INVALID_REQUEST", "Malformed request", _request_id(request.headers.get("X-Request-ID")))


@app.exception_handler(Exception)
async def store_error_handler(request: Request, exc: Exception):
    # Redis connection errors surface here; anything else is still reported in the envelope
    code = "STATE_STORE_UNAVAILABLE" if "redis" in type(exc).__module__ else "INTERNAL_ERROR"
    status = 503 if code == "STATE_STORE_UNAVAILABLE" else 500
    return fail(status, code, str(exc) or type(exc).__name__, _request_id(request.headers.get("X-Request-ID")))


# ---------------------------------------------------------------------------
# Channel permissions (docs/roles/05-role-chat-statestore-qa.md section 2.2)
# ---------------------------------------------------------------------------

def can_read(channel: str, player: Dict[str, Any]) -> bool:
    alive = player.get("alive", True)
    if channel == "PUBLIC":
        return True
    if channel == "WOLF":
        return alive and player.get("role") == "WEREWOLF"
    if channel == "DEAD":
        return not alive
    return False


def can_post(channel: str, player: Dict[str, Any], phase: Optional[str]) -> Tuple[bool, str]:
    alive = player.get("alive", True)
    if channel == "PUBLIC":
        return alive and phase == "DAY", "Only living players can post in PUBLIC chat during DAY"
    if channel == "WOLF":
        return (alive and player.get("role") == "WEREWOLF" and phase == "NIGHT",
                "Only living werewolves can post in WOLF chat during NIGHT")
    if channel == "DEAD":
        return not alive, "Only dead players can post in DEAD chat"
    return False, "Unknown channel"


async def authenticate(room_id: str, authorization: Optional[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Resolves the caller strictly from the bearer token. Returns (room, caller_player)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise ChatError(401, "MISSING_TOKEN", "Missing Bearer token")
    token = authorization[len("Bearer "):].strip()
    session = await store.get_player_session(token)
    if not session or session.get("room_id") != room_id:
        raise ChatError(401, "INVALID_TOKEN", "Session not found for token")
    room = await store.get_room(room_id)
    if room is None:
        raise ChatError(404, "ROOM_NOT_FOUND", "Room not found")
    player = room.get("players", {}).get(session.get("player_id"))
    if player is None:
        raise ChatError(401, "INVALID_TOKEN", "Player is not part of this room")
    return room, player


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health/live")
async def health_live():
    return {"ok": True, "status": "UP", "service": "chat", "trace": [get_service_trace("chat")]}


@app.get("/health/ready")
async def health_ready():
    try:
        await store.get_room("__health__")
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "status": "DOWN", "service": "chat", "error": str(exc),
                     "trace": [get_service_trace("chat")]},
        )
    return {"ok": True, "status": "UP", "service": "chat", "trace": [get_service_trace("chat")]}


@app.get("/api/chat/rooms/{room_id}/messages")
async def get_messages(
    room_id: str,
    after_id: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=CHAT_HISTORY_LIMIT),
    authorization: Optional[str] = Header(None),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
):
    rid = _request_id(x_request_id)
    _, player = await authenticate(room_id, authorization)
    # Filter before applying the limit: otherwise a page full of hidden WOLF/DEAD
    # messages would pin the caller's after_id and hide newer visible messages.
    raw_messages = await store.get_chat(room_id, after_id=after_id, limit=CHAT_HISTORY_LIMIT)
    visible = [m for m in raw_messages if can_read(m.get("channel"), player)]
    return ok({"messages": visible[:limit]}, rid)


@app.post("/api/chat/rooms/{room_id}/messages")
async def send_message(
    room_id: str,
    payload: SendMessageRequest,
    authorization: Optional[str] = Header(None),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
):
    rid = _request_id(x_request_id)
    room, player = await authenticate(room_id, authorization)
    allowed, reason = can_post(payload.channel, player, room.get("phase"))
    if not allowed:
        raise ChatError(403, "FORBIDDEN_CHANNEL", reason)

    stored = await store.append_chat(room_id, {
        "channel": payload.channel,
        "sender_id": player["player_id"],
        "sender_name": player.get("name", "Unknown"),
        "text": payload.text,
        "created_at": int(time.time()),
    })
    return ok({"message_id": stored["message_id"], "status": "DELIVERED"}, rid)
