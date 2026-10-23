# API Contract & Schema Specification (Source of Truth)

> **Status:** FROZEN (MVP Baseline)  
> **Target Audience:** All Backend Developers (Gateway, Lobby, GameMaster, Chat), Frontend Lead  
> **Related Files:** [02-game-rules-and-ux.md](../docs/02-game-rules-and-ux.md), [01-architecture-infra.md](../docs/01-architecture-infra.md)

---

## 1. Global Request Flow & Network Trace Contract

Every client HTTP request passes through `gateway` before being proxied to a backend service. Direct external access to internal backend microservices or Redis is strictly prohibited.

### 1.1 Pod & Node Identity Injection (Downward API)
Every container inspects its physical runtime placement via the Kubernetes Downward API:

```yaml
env:
  - name: POD_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.name
  - name: NODE_NAME
    valueFrom:
      fieldRef:
        fieldPath: spec.nodeName
```

### 1.2 Trace Assembly Rules
1. **`X-Request-ID` Propagation:** The `gateway` generates a UUID string (`req-xxxx`) for every inbound client request and attaches it as an HTTP header `X-Request-ID` when proxying internally.
2. **Trace Header Collection:** Each backend service returns an HTTP header or JSON trace object containing:
   `{"service": "<service_name>", "pod": "<POD_NAME>", "node": "<NODE_NAME>"}`
3. **Trace Array Ingestion:** The `gateway` prepends its own identity to the trace array and appends all upstream hops in chronological order.
4. **SDN Validation Rule:** In the response trace, `trace[0].node` (Gateway node) and `trace[1].node` (Handler node) **must be different** to prove cross-node execution.

---

## 2. Standard Response & Error Envelopes

All JSON responses (success or error) MUST adhere to the standard envelope structure.

### 2.1 Success Envelope
```json
{
  "ok": true,
  "data": { ... },
  "request_id": "req-9c8e1a2b",
  "trace": [
    { "service": "gateway",    "pod": "gateway-7f89d-2k8l",    "node": "pi-01" },
    { "service": "gamemaster", "pod": "gamemaster-5b4d-9mxq", "node": "pi-04" }
  ]
}
```

### 2.2 Error Envelope
```json
{
  "ok": false,
  "error": {
    "code": "ROOM_FULL",
    "message": "This room has reached the maximum capacity of 6 players."
  },
  "request_id": "req-9c8e1a2b",
  "trace": [
    { "service": "gateway", "pod": "gateway-7f89d-2k8l", "node": "pi-01" },
    { "service": "lobby",   "pod": "lobby-6c5d-x49p",     "node": "pi-02" }
  ]
}
```

### 2.3 Standard HTTP Status Codes

| HTTP Status | Error Code | Trigger Condition |
|:---:|---|---|
| **`400`** | `INVALID_REQUEST` | Malformed JSON, target player is already dead, or invalid target format. |
| **`401`** | `INVALID_TOKEN` / `MISSING_TOKEN` | Bearer token missing, expired, or invalid. |
| **`403`** | `HOST_ONLY` | Non-host player attempted to start game. |
| **`403`** | `FORBIDDEN_ROLE` | Player attempted an action not permitted for their role (e.g. Villager night action). |
| **`403`** | `FORBIDDEN_CHANNEL` | Sender not permitted to post in requested channel (e.g., dead player in `PUBLIC`, non-wolf in `WOLF`). |
| **`404`** | `ROOM_NOT_FOUND` | Room code does not exist. |
| **`409`** | `ROOM_FULL` | Room already has 6 players. |
| **`409`** | `GAME_ALREADY_STARTED` | Player attempted to join a room whose phase is not `WAITING`. |
| **`409`** | `ACTION_ALREADY_SUBMITTED` | Conflicting action submitted in the same phase. |
| **`409`** | `PHASE_VERSION_CONFLICT` | Action submitted with a stale `phase_version`. |
| **`503`** | `STATE_STORE_UNAVAILABLE` | Redis connection timeout or Redis unavailable. |

---

## 3. Authentication & Player Session

1. **Token Issuance:** Upon room creation or join, the Lobby service generates a cryptographically random string (e.g., `secrets.token_urlsafe(32)`).
2. **Session Storage:** A mapping is stored in Redis:
   - Key: `session:{token_hash}` $\rightarrow$ Value: `{"room_id": "WOLF", "player_id": "p1", "created_at": 1720000000}`
3. **Client Authorization:** Frontend must send the token in the standard HTTP header on all authenticated calls:
   ```text
   Authorization: Bearer <player_token>
   ```
4. **Security Invariant:** Server services resolve identity strictly via the token hash in Redis. Query string `player_id` parameters are never trusted for authorization.

---

## 4. StateStore Architecture & Data Model

### 4.1 Redis Key Topology

| Redis Key Pattern | Redis Type | Description & Retention Policy |
|---|---|---|
| `room:{room_id}:state` | String (JSON) | Complete authoritative internal room state. TTL = 24h. |
| `room:{room_id}:chat` | List (JSON) | Append-only ordered message stream (capped at 200 items). |
| `room:{room_id}:chat_seq` | Integer | Counter providing incremental integer `message_id`. |
| `session:{token_hash}` | String (JSON) | Token-to-player identity mapping. TTL = 24h. |

### 4.2 InternalRoomState Schema (Redis Internal)
```json
{
  "room_id": "WOLF",
  "version": 14,
  "phase": "NIGHT",
  "day_count": 1,
  "phase_end_time": 1720000045,
  "winner": null,
  "announcement": "Night 1 has fallen over the village.",
  "host_player_id": "p1",
  "players": {
    "p1": { "player_id": "p1", "name": "Alice", "role": "WEREWOLF", "alive": true, "is_host": true },
    "p2": { "player_id": "p2", "name": "Bob",   "role": "SEER",     "alive": true, "is_host": false },
    "p3": { "player_id": "p3", "name": "Carol", "role": "DOCTOR",   "alive": true, "is_host": false },
    "p4": { "player_id": "p4", "name": "Dave",  "role": "VILLAGER", "alive": true, "is_host": false },
    "p5": { "player_id": "p5", "name": "Eve",   "role": "VILLAGER", "alive": true, "is_host": false }
  },
  "night_actions": {
    "wolf_votes": { "p1": "p4" },
    "doctor_target": "p4",
    "seer_target": "p1",
    "seer_result_by_player": { "p2": "WEREWOLF" }
  },
  "day_votes": {},
  "created_at": 1720000000,
  "updated_at": 1720000010
}
```

### 4.3 Python StateStore Interface (`common/state_store.py`)
All services interact with state via this abstract interface:

```python
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional

class StateStore(ABC):
    @abstractmethod
    async def get_room(self, room_id: str) -> Optional[Dict]: ...

    @abstractmethod
    async def create_room(self, room_id: str, initial_state: Dict) -> bool: ...

    @abstractmethod
    async def update_room(self, room_id: str, mutator: Callable[[Dict], Dict]) -> Dict:
        """
        Executes atomic mutation using Redis WATCH/MULTI/EXEC (CAS).
        Raises StateConflictError if conflicting updates occur.
        """
        ...

    @abstractmethod
    async def get_player_session(self, token: str) -> Optional[Dict]: ...

    @abstractmethod
    async def create_player_session(self, token: str, session_data: Dict) -> None: ...

    @abstractmethod
    async def append_chat(self, room_id: str, message: Dict) -> Dict: ...

    @abstractmethod
    async def get_chat(self, room_id: str, after_id: int = 0, limit: int = 100) -> List[Dict]: ...
```

---

## 5. API Endpoints Specification

### 5.1 Lobby Service Endpoints

#### `POST /api/lobby/rooms`
- **Auth:** None
- **Request Body:**
  ```json
  { "name": "Alice" }
  ```
- **Response `data`:**
  ```json
  {
    "room_id": "WOLF",
    "player_id": "p1",
    "player_token": "tok_9a8b7c6d5e",
    "is_host": true
  }
  ```

#### `POST /api/lobby/rooms/{room_id}/join`
- **Auth:** None
- **Request Body:**
  ```json
  { "name": "Bob" }
  ```
- **Response `data`:**
  ```json
  {
    "room_id": "WOLF",
    "player_id": "p2",
    "player_token": "tok_1f2e3d4c5b",
    "is_host": false
  }
  ```

#### `GET /api/lobby/rooms/{room_id}`
- **Auth:** Bearer Token
- **Response `data`:**
  ```json
  {
    "room_id": "WOLF",
    "phase": "WAITING",
    "host_player_id": "p1",
    "players": [
      { "player_id": "p1", "name": "Alice", "is_host": true },
      { "player_id": "p2", "name": "Bob",   "is_host": false }
    ]
  }
  ```

#### `POST /api/lobby/rooms/{room_id}/start`
- **Auth:** Bearer Token (Host Only)
- **Validation:** Total players must be between 4 and 6. Calls GameMaster internal API.
- **Response `data`:**
  ```json
  { "status": "STARTED" }
  ```

---

### 5.2 GameMaster Service Endpoints

#### `GET /api/game/rooms/{room_id}/state`
- **Auth:** Bearer Token
- **Behavior:** Executes `advance_if_expired()` on server clock. Sanitizes internal state into a role-safe `PlayerView`.
- **Response `data`:**
  ```json
  {
    "room_id": "WOLF",
    "phase": "NIGHT",
    "day_count": 1,
    "phase_version": 14,
    "phase_end_time": 1720000045,
    "winner": null,
    "announcement": "Night 1 has begun.",
    "me": {
      "player_id": "p2",
      "name": "Bob",
      "role": "SEER",
      "alive": true,
      "private_info": {
        "seer_result": { "target_id": "p1", "result": "WEREWOLF" }
      }
    },
    "players": [
      { "player_id": "p1", "name": "Alice", "alive": true, "role": null },
      { "player_id": "p2", "name": "Bob",   "alive": true, "role": "SEER" },
      { "player_id": "p3", "name": "Carol", "alive": true, "role": null },
      { "player_id": "p4", "name": "Dave",  "alive": false, "role": null },
      { "player_id": "p5", "name": "Eve",   "alive": true, "role": null }
    ]
  }
  ```
  *(Note: Other players' roles are strictly `null` until `phase == ENDED`, except for Werewolves who can see fellow Werewolves).*

#### `POST /api/game/rooms/{room_id}/night-actions`
- **Auth:** Bearer Token
- **Request Body:**
  ```json
  {
    "phase_version": 14,
    "action": "SEER_CHECK",
    "target_id": "p1"
  }
  ```
- **Response `data`:**
  ```json
  {
    "status": "ACCEPTED",
    "action": "SEER_CHECK",
    "target_id": "p1"
  }
  ```
- **Canonical `action` values** (exact strings; one per role, anything else returns `403 FORBIDDEN_ROLE`):

  | Role | `action` | Target rule |
  |---|---|---|
  | `WEREWOLF` | `WEREWOLF_KILL` | Living player, not self |
  | `DOCTOR` | `DOCTOR_PROTECT` | Living player, self allowed |
  | `SEER` | `SEER_CHECK` | Living player, not self |

  `VILLAGER` has no night action.

#### `POST /api/game/rooms/{room_id}/vote`
- **Auth:** Bearer Token
- **Request Body:**
  ```json
  {
    "phase_version": 15,
    "target_id": "p1"
  }
  ```
  *(Set `target_id: "SKIP"` to cast a skip/abstain ballot).*
- **Response `data`:**
  ```json
  {
    "status": "VOTE_CAST",
    "target_id": "p1"
  }
  ```

---

### 5.3 Chat Service Endpoints

#### `GET /api/chat/rooms/{room_id}/messages`
- **Query Params:** `after_id` (integer, default `0`), `limit` (integer, default `100`)
- **Auth:** Bearer Token
- **Behavior:** Returns only messages from channels the caller is authorized to view.
- **Response `data`:**
  ```json
  {
    "messages": [
      {
        "message_id": 12,
        "channel": "PUBLIC",
        "sender_id": "p1",
        "sender_name": "Alice",
        "text": "Who should we execute today?",
        "created_at": 1720000080
      }
    ]
  }
  ```

#### `POST /api/chat/rooms/{room_id}/messages`
- **Auth:** Bearer Token
- **Request Body:**
  ```json
  {
    "channel": "PUBLIC",
    "text": "I suspect Alice is the werewolf!"
  }
  ```
- **Validation:**
  - `PUBLIC`: Living players during `DAY`.
  - `WOLF`: Living werewolves during `NIGHT`.
  - `DEAD`: Dead players in post-mortem spectator chat.
- **Response `data`:**
  ```json
  {
    "message_id": 13,
    "status": "DELIVERED"
  }
  ```

---

### 5.4 Internal & Health Endpoints

#### `POST /api/demo/rooms/{room_id}/force-next`
- **Caller:** Demo operator only (routed by `gateway` to `gamemaster`).
- **Auth:** Header `X-Demo-Secret: <DEMO_SECRET>`; enabled only when `DEMO_MODE=true`. Otherwise `403 FORBIDDEN`.
- **Behavior:** Immediately advances the room to its next phase (resolving the current one) instead of waiting for the timer.
- **Response `data`:**
  ```json
  { "status": "ADVANCED", "phase": "DAY", "phase_version": 15, "announcement": "Dawn breaks. ..." }
  ```

#### `POST /internal/rooms/{room_id}/initialize`
- **Caller:** `lobby` Service only.
- **Behavior:** Transitions room from `WAITING` to `NIGHT`, randomly assigns roles, sets `phase_end_time`.

#### `GET /health/live` & `GET /health/ready`
- Implemented on all microservices for Kubernetes probes.
- `/health/ready` tests Redis socket connectivity for services depending on the data layer.
