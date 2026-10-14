# AI Agent Guide — Role 5: Chat, Shared StateStore & Integration QA Lead

> **Role Focus:** Data Persistence Layer (`StateStore`), Redis Optimistic Concurrency (CAS), Chat Authorization (`PUBLIC`, `WOLF`, `DEAD`), Docker Compose Integration, and Concurrency Testing.  
> **Master Context:** Read [00-agent-system-prompt.md](00-agent-system-prompt.md), [api-contract.md](../../contracts/api-contract.md), and [03-team-workflow.md](../03-team-workflow.md).

---

## 1. Role Scope & Owned Files

As the Chat, StateStore & QA Lead, you hold the foundational responsibility for shared data integrity across all microservices, ensuring thread-safe/atomic room updates, role-segregated communications, and the full multi-service Docker Compose development environment.

### Files You Own
- `common/state_store.py` (Abstract interface, `InMemoryStateStore`, `RedisStateStore`)
- `services/chat/` (FastAPI chat application, Dockerfile, requirements.txt)
- `docker-compose.dev.yml` (Local full-stack testing environment)
- `tests/integration/` (Redis integration tests, concurrency tests, CAS conflict validation)
- `tests/unit/test_chat.py`
- `tests/unit/test_statestore.py`

### Files You Must NOT Modify
- Do not modify game rule transitions in `services/gamemaster/`.
- Do not modify Kubernetes deployment manifests in `k8s/` (Role 1).

---

## 2. Technical Specifications & Critical Components

### 2.1 StateStore Architecture (`common/state_store.py`)
You must provide two implementations of the `StateStore` interface on **Day 1**:
1. **`InMemoryStateStore`:** Uses thread-safe Python dictionaries. Used by other team members for offline unit testing without spinning up Redis.
2. **`RedisStateStore`:** Uses `redis.asyncio`. Must implement **Optimistic Concurrency Control (CAS)** for `update_room`:
   - Uses `WATCH room:{room_id}:state`
   - Reads current JSON and version.
   - Applies the pure mutation function: `new_state = mutator(current_state)`
   - Increments `version += 1` and updates `updated_at`.
   - Executes `MULTI` $\rightarrow$ `SET room:{room_id}:state <json>` $\rightarrow$ `EXEC`.
   - If a `WatchError` occurs (another request updated the room concurrently), retries up to 3 times before raising `StateConflictError` (mapped to HTTP `409 STATE_CONFLICT`).

### 2.2 Chat Service (`services/chat`)
1. **Channels & Permissions Matrix:**

| Channel | Allowed Phase | Who Can Read | Who Can Post |
|---|---|---|---|
| `PUBLIC` | `DAY` | All players (living and dead) | **Living players only** during `DAY`. |
| `WOLF` | `NIGHT` | **Living Werewolves only** | **Living Werewolves only** during `NIGHT`. |
| `DEAD` | Any | **Dead players only** | **Dead players only** (Spectator post-mortem). |

2. **Endpoints:**
   - `GET /api/chat/rooms/{room_id}/messages?after_id={id}&limit={n}`
     - Validates caller session token against Redis.
     - Retrieves recent messages from Redis List (`room:{room_id}:chat`).
     - Filters out messages from channels the caller is unauthorized to view.
   - `POST /api/chat/rooms/{room_id}/messages`
     - Validates payload: `{"channel": "PUBLIC", "text": "..."}`.
     - Text length: 1–500 chars (trimmed).
     - Checks sender authorization against latest `InternalRoomState`.
     - Increments `room:{room_id}:chat_seq` to assign a strictly ascending integer `message_id`.
     - Appends message to Redis List (capped at 200 items using `LTRIM`).

---

## 3. Local Development & Testing Instructions

### 3.1 Testing `StateStore` & Redis CAS Concurrency
Start local Redis:
```bash
docker run -d --name test-redis -p 6379:6379 redis:7.2-alpine
```

Run concurrency tests in `tests/integration/test_concurrency.py`:
```python
import asyncio
import pytest
from common.state_store import RedisStateStore

@pytest.mark.asyncio
async def test_concurrent_votes_no_lost_updates():
    store = RedisStateStore("redis://localhost:6379")
    await store.create_room("TEST", {"room_id": "TEST", "version": 1, "day_votes": {}})

    async def submit_vote(player_id, target_id):
        def vote_mutator(state):
            state["day_votes"][player_id] = target_id
            return state
        await store.update_room("TEST", vote_mutator)

    # 5 players vote simultaneously
    await asyncio.gather(
        submit_vote("p1", "p2"),
        submit_vote("p2", "p3"),
        submit_vote("p3", "p4"),
        submit_vote("p4", "p5"),
        submit_vote("p5", "p1")
    )

    final_room = await store.get_room("TEST")
    assert len(final_room["day_votes"]) == 5  # Zero lost updates!
```

### 3.2 Running the Full Stack via Docker Compose
Verify that all 5 microservices collaborate successfully:
```bash
docker compose -f docker-compose.dev.yml up --build
```
This boots up:
- `redis:7.2-alpine` on port `6379`
- `services/lobby` on internal port `8000`
- `services/gamemaster` on internal port `8000`
- `services/chat` on internal port `8000`
- `services/frontend` on internal port `80`
- `services/gateway` on external port `8080`

Test in your browser at `http://localhost:8080`.

---

## 4. Key Implementation Patterns

### 4.1 Redis CAS `update_room` Implementation Pattern
```python
import json
import redis.asyncio as aioredis
from common.exceptions import StateConflictError

class RedisStateStore(StateStore):
    def __init__(self, redis_url: str):
        self.redis = aioredis.from_url(redis_url, decode_responses=True)

    async def update_room(self, room_id: str, mutator, max_retries: int = 3) -> dict:
        key = f"room:{room_id}:state"
        for attempt in range(max_retries):
            async with self.redis.pipeline() as pipe:
                try:
                    await pipe.watch(key)
                    raw = await pipe.get(key)
                    if not raw:
                        raise ValueError(f"Room {room_id} not found")
                    state = json.loads(raw)

                    # Apply mutation
                    updated_state = mutator(state)
                    updated_state["version"] = state.get("version", 0) + 1

                    pipe.multi()
                    pipe.set(key, json.dumps(updated_state))
                    await pipe.execute()
                    return updated_state
                except aioredis.WatchError:
                    if attempt == max_retries - 1:
                        raise StateConflictError("Concurrent room update collision")
                    continue
```

---

## 5. Ready-to-Use Agent Prompt

```text
You are acting as the Chat, Shared StateStore & QA Lead (Role 5) for the Werewolf SDS project.
Your task is to build common/state_store.py (both InMemoryStateStore and RedisStateStore with WATCH/MULTI/EXEC CAS),
services/chat/app, docker-compose.dev.yml, and tests/integration/test_concurrency.py.
Follow docs/roles/05-role-chat-statestore-qa.md, docs/03-team-workflow.md, and contracts/api-contract.md.
Ensure role-based chat channel authorization (PUBLIC, WOLF, DEAD) is strictly verified server-side,
and that concurrent state mutations never lose updates.
```
