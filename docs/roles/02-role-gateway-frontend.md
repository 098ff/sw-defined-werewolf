# AI Agent Guide — Role 2: Gateway & Frontend Lead

> **Role Focus:** Ingress Proxy (`gateway`), Downward API Trace Aggregation, and Web UI (`frontend`).  
> **Master Context:** Read [00-agent-system-prompt.md](00-agent-system-prompt.md), [02-game-rules-and-ux.md](../02-game-rules-and-ux.md), and [api-contract.md](../../contracts/api-contract.md).

---

## 1. Role Scope & Owned Files

As the Gateway & Frontend Lead, you build the client-facing presentation layer and the reverse-proxy entrypoint that proves cross-node SDN execution.

### Files You Own
- `services/gateway/` (FastAPI async reverse-proxy, Dockerfile, requirements.txt)
- `services/frontend/` (React + Vite SPA, Tailwind/CSS, Nginx configuration, Dockerfile)
- `tests/unit/test_gateway.py`
- `tests/contract/test_envelope.py`

### Files You Must NOT Modify
- Do not modify backend game rules in `services/gamemaster/` or `services/lobby/`.
- Do not write custom Redis operations (Gateway is 100% stateless).

---

## 2. Technical Specifications & Critical Rules

### 2.1 Gateway (`services/gateway`)
1. **Framework:** Python 3.11/3.12 + FastAPI + `httpx.AsyncClient`.
2. **Reverse Proxy Routing Table:**
   - `GET /` and static paths (`/assets/*`, `/favicon.ico`) $\rightarrow$ Proxy to `http://frontend:80`
   - `/api/lobby/*` $\rightarrow$ Proxy to `http://lobby:8000`
   - `/api/game/*` $\rightarrow$ Proxy to `http://gamemaster:8000`
   - `/api/chat/*` $\rightarrow$ Proxy to `http://chat:8000`
3. **Trace Header & Trace Envelope Assembly:**
   - Generate a UUID for each request (`req-xxxx`) and attach `X-Request-ID` to all upstream calls.
   - Read own identity from environment: `POD_NAME = os.getenv("POD_NAME", "gateway-local")`, `NODE_NAME = os.getenv("NODE_NAME", "node-local")`.
   - Read upstream trace headers/body, prepend own hop:
     `{"service": "gateway", "pod": POD_NAME, "node": NODE_NAME}`
   - Ensure the JSON response sent to client contains:
     ```json
     { "ok": true, "data": ..., "request_id": "req-xxxx", "trace": [ {gateway_hop}, {handler_hop} ] }
     ```
4. **Error Forwarding:** Forward status codes (`400`, `401`, `403`, `404`, `409`) directly from backends without swallowing error details. If upstream fails (timeout or connection refused), return `503 SERVICE_UNAVAILABLE`.

### 2.2 Frontend (`services/frontend`)
1. **Stack:** React 18 + Vite + Tailwind CSS + Lucide Icons + Nginx Alpine base image.
2. **Screens to Implement:**
   - **Lobby View:** Displays Room Code, Player list with ready badges, Host "Start Game" button (disabled if players < 4).
   - **Identity Banner ("My Role"):** Displays secret role, alignment, and description (hidden from other players).
   - **Night Action Controls:** Radio options for Werewolf target, Doctor target, Seer inspect.
   - **Day Controls:** Voting grid for living candidates + explicit "Skip Vote" button.
   - **Chat Panel:** Tabs for `PUBLIC` (Day), `WOLF` (Night Werewolf only), `DEAD` (Dead spectators).
   - **Game Over Modal:** Announces winning team and renders full table revealing everyone's real role.
   - **Collapsible System Trace HUD:** Floating badge at bottom of screen displaying:
     `Path: gateway (<node1>) ➔ <service> (<node2>) | Trace verified: Cross-Node OK`
3. **REST Polling Engine:**
   - Poll `GET /api/game/rooms/{room_id}/state` every **2000ms**.
   - Poll `GET /api/chat/rooms/{room_id}/messages?after_id={last_id}` every **2000ms**.
   - Store `player_token` and `room_id` in `sessionStorage` so refreshing the browser retains the game session.

---

## 3. Local Development & Testing Instructions

You can develop both Gateway and Frontend completely offline without Kubernetes or finished backend services.

### 3.1 Running Frontend in Development Mode
```bash
cd services/frontend
npm install
npm run dev
# Starts Vite dev server at http://localhost:5173
```

### 3.2 Running Gateway Standalone with Mock Backends
Create a lightweight mock script `tests/mock_backend.py` returning sample contracts:
```python
# Run mock backend on port 8000
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/game/rooms/{room_id}/state")
def mock_state(room_id: str):
    return {
        "ok": True,
        "data": {
            "room_id": room_id,
            "phase": "NIGHT",
            "phase_version": 1,
            "phase_end_time": 9999999999,
            "me": {"player_id": "p1", "name": "Alice", "role": "SEER", "alive": True},
            "players": [{"player_id": "p1", "name": "Alice", "alive": True, "role": "SEER"}]
        },
        "trace": [{"service": "gamemaster", "pod": "mock-gm", "node": "mock-pi"}]
    }
```
Run Gateway pointing to mock:
```bash
cd services/gateway
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GAMEMASTER_URL="http://localhost:8000"
uvicorn app.main:app --port 8080 --reload
```
Open `http://localhost:8080/api/game/rooms/WOLF/state` and verify the `trace` array contains both `gateway` and `gamemaster`.

---

## 4. Key Implementation Patterns

### 4.1 Downward API Trace Reader (`common/trace.py`)
```python
import os

def get_service_trace(service_name: str) -> dict:
    return {
        "service": service_name,
        "pod": os.getenv("POD_NAME", f"{service_name}-local"),
        "node": os.getenv("NODE_NAME", "node-local")
    }
```

### 4.2 Frontend Polling Hook (React)
```typescript
import { useEffect, useRef } from "react";

export function useGamePolling(roomId: string, token: string, onUpdate: (state: any) => void) {
  const timerRef = useRef<NodeJS.Timeout>();

  useEffect(() => {
    if (!roomId || !token) return;

    const fetchState = async () => {
      try {
        const res = await fetch(`/api/game/rooms/${roomId}/state`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        const json = await res.json();
        if (json.ok) onUpdate(json.data, json.trace);
      } catch (err) {
        console.warn("Polling error (reconnecting):", err);
      }
    };

    fetchState();
    timerRef.current = setInterval(fetchState, 2000);
    return () => clearInterval(timerRef.current);
  }, [roomId, token]);
}
```

---

## 5. Ready-to-Use Agent Prompt

```text
You are acting as the Gateway and Frontend Lead (Role 2) for the Werewolf SDS project.
Your task is to build services/gateway and services/frontend.
Follow docs/roles/02-role-gateway-frontend.md, docs/02-game-rules-and-ux.md, and contracts/api-contract.md.
Never use WebSockets. Ensure 2-second REST polling, the collapsible System Trace HUD on the UI,
and ensure the Gateway attaches X-Request-ID and aggregates the Downward API trace array.
```
