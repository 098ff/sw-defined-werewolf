# AI Agent Guide — Role 3: Lobby Service Lead

> **Role Focus:** Pre-game Room Lifecycle, Room Codes, Session Tokens, Capacity Enforcement (`4–6 players`), and Game Start Handoff.  
> **Master Context:** Read [00-agent-system-prompt.md](00-agent-system-prompt.md) and [api-contract.md](../../contracts/api-contract.md).

---

## 1. Role Scope & Owned Files

As the Lobby Service Lead, you implement the room creation, player joining, authentication token generation, and the handoff to GameMaster when the game begins.

### Files You Own
- `services/lobby/` (FastAPI application, Dockerfile, requirements.txt)
- `tests/unit/test_lobby.py`

### Files You Must NOT Modify
- Do not modify game rule resolution in `services/gamemaster/`.
- Do not modify `common/state_store.py` (owned by Role 5; you consume the interface).
- Do not change API schemas in `contracts/api-contract.md`.

---

## 2. Technical Specifications & Endpoints

### 2.1 API Endpoints to Implement

| Method | Path | Auth Required | Description |
|---|---|---|---|
| `POST` | `/api/lobby/rooms` | None | Creates a new room with a random 4-char uppercase code (e.g., `WOLF`). The creator becomes the Host and receives a secret `player_token`. |
| `POST` | `/api/lobby/rooms/{room_id}/join` | None | Joins an existing room if phase is `WAITING`. Enforces unique names and max 6 players. Issues a `player_token`. |
| `GET` | `/api/lobby/rooms/{room_id}` | Bearer Token | Returns public lobby state (room ID, phase, host player ID, list of players). Does NOT leak roles. |
| `POST` | `/api/lobby/rooms/{room_id}/start` | Bearer Token (Host) | Validates caller is Host and player count is between 4 and 6. Invokes GameMaster internal initialize API. |
| `GET` | `/health/live` & `/health/ready` | None | Kubernetes readiness and liveness probes. |

### 2.2 Critical Invariants & Validations
1. **Player Count Boundaries (Strict):**
   - Less than 4 players: `POST /start` MUST reject with HTTP `400 INVALID_REQUEST` (`"At least 4 players required to start"`).
   - Exactly 4, 5, or 6 players: `POST /start` is permitted.
   - More than 6 players: `POST /join` MUST reject with HTTP `409 ROOM_FULL`.
2. **Phase Validation:**
   - Once the game has started (phase is `NIGHT`, `DAY`, or `ENDED`), any join attempt MUST reject with HTTP `409 GAME_ALREADY_STARTED`.
3. **Session Token Security:**
   - Generate cryptographically secure tokens: `secrets.token_urlsafe(32)`.
   - Store session mapping via `state_store.create_player_session(token, session_data)`.
   - Never trust `player_id` passed in query parameters; always authenticate via the `Authorization: Bearer <token>` header.
4. **Trace Injection:**
   - Always read Downward API environment variables (`POD_NAME`, `NODE_NAME`) and attach service trace to all responses.

---

## 3. Local Development & Testing Instructions

You can develop and unit test the Lobby service **100% standalone** without spinning up Redis, Kubernetes, or other services.

### 3.1 Setup Virtual Environment
```bash
cd services/lobby
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3.2 Running with `InMemoryStateStore`
Set the environment variable `STATE_STORE_BACKEND=in_memory`:
```bash
export STATE_STORE_BACKEND=in_memory
export GAMEMASTER_URL="http://localhost:8002"
uvicorn app.main:app --port 8001 --reload
```
Open your browser at `http://localhost:8001/docs` to test endpoints via Swagger UI.

### 3.3 Running Unit Tests
Write comprehensive unit tests in `tests/unit/test_lobby.py` using `pytest` and `httpx.AsyncClient`:
```python
import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_room_lifecycle():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # 1. Create Room
        res = await ac.post("/api/lobby/rooms", json={"name": "Alice"})
        assert res.status_code == 200
        data = res.json()["data"]
        room_id = data["room_id"]
        host_token = data["player_token"]

        # 2. Join 3 players (total 4)
        for name in ["Bob", "Carol", "Dave"]:
            join_res = await ac.post(f"/api/lobby/rooms/{room_id}/join", json={"name": name})
            assert join_res.status_code == 200

        # 3. Start Game
        start_res = await ac.post(
            f"/api/lobby/rooms/{room_id}/start",
            headers={"Authorization": f"Bearer {host_token}"}
        )
        assert start_res.status_code == 200
```
Run tests:
```bash
pytest tests/unit/test_lobby.py
```

---

## 4. Key Implementation Patterns

### 4.1 Dependency Injection for StateStore
```python
import os
from common.state_store import StateStore, InMemoryStateStore, RedisStateStore

_store: StateStore = None

def get_state_store() -> StateStore:
    global _store
    if _store is None:
        backend = os.getenv("STATE_STORE_BACKEND", "redis")
        if backend == "in_memory":
            _store = InMemoryStateStore()
        else:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            _store = RedisStateStore(redis_url)
    return _store
```

### 4.2 Standard Endpoint Wrapper
```python
from fastapi import APIRouter, Depends, HTTPException, Header
from common.trace import get_service_trace

router = APIRouter(prefix="/api/lobby")

@router.post("/rooms")
async def create_room(payload: CreateRoomRequest, store: StateStore = Depends(get_state_store)):
    # ... generate room_id, player_id, token, initial_state ...
    await store.create_room(room_id, initial_state)
    await store.create_player_session(token, {"room_id": room_id, "player_id": player_id})

    return {
        "ok": True,
        "data": {
            "room_id": room_id,
            "player_id": player_id,
            "player_token": token,
            "is_host": True
        },
        "trace": [get_service_trace("lobby")]
    }
```

---

## 5. Ready-to-Use Agent Prompt

```text
You are acting as the Lobby Service Engineer (Role 3) for the Werewolf SDS project.
Your task is to build services/lobby/app and tests/unit/test_lobby.py.
Follow docs/roles/03-role-lobby.md, docs/02-game-rules-and-ux.md, and contracts/api-contract.md.
Ensure room codes are 4 random uppercase chars, player limit is strictly 4 to 6, start requires >= 4 players
and host authorization, sessions use secure tokens, and responses follow the standard envelope with trace.
```
