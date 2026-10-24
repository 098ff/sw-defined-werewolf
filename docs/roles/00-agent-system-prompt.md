# Central Agent Guidelines & Global Project Invariants

> **Target Audience:** Any AI / LLM Agent (ChatGPT, Claude, Gemini, Antigravity, Cursor, Copilot) assigned to work on any part of the Werewolf SDS Project.  
> **How to Use:** When starting a chat with an AI assistant, reference this file along with your specific role document in `docs/roles/`.

---

## 1. Project Context & High-Level Architecture

You are pair-programming on an academic project for **2110415 Software-Defined Systems**. The application is a **Multiplayer Werewolf Game (4–6 players)** deployed on an on-premises Bare-Metal Kubernetes cluster consisting of:
- **1x Notebook Virtual Machine (Ubuntu 64-bit):** K3s Control-Plane (Master) node with Bridged Networking.
- **5x Raspberry Pi 3 B+:** K3s Worker nodes (ARM64, 1GB RAM each) connected via an Ethernet switch.
- **5 Custom Microservices:** `gateway`, `frontend`, `lobby`, `gamemaster`, `chat` (1 replica each on Pi workers).
- **1 Infrastructure Component:** `redis:7.2-alpine` pinned strictly to the Master VM with persistent storage.
- **Load Balancer:** MetalLB Layer-2 Virtual IP (`192.168.0.240`).

---

## 2. Universal Invariants (Strict Architectural Rules)

Regardless of which service or role you are implementing, you **MUST NEVER violate** these invariants:

1. **No WebSockets (REST Polling Only):** All real-time updates use HTTP REST polling (2-second interval). Do not implement WebSockets, Server-Sent Events (SSE), or long-polling. This is a deliberate design decision to prevent socket deadlocks during node failure events.
2. **Standard Response Envelope:** Every HTTP response (except static assets) MUST return the standard envelope:
   ```json
   {
     "ok": true,
     "data": { ... },
     "request_id": "req-xxxx",
     "trace": [ ... ]
   }
   ```
   Errors must return `ok: false`, with standard codes (`400`, `401`, `403`, `404`, `409`, `503`). See [api-contract.md](../../contracts/api-contract.md).
3. **Downward API Trace Injection:** Containers that process HTTP requests must read `POD_NAME` and `NODE_NAME` from environment variables provided by Kubernetes Downward API and return them in the trace metadata.
4. **No Direct Backend/Redis Exposure:** Only `gateway` receives traffic from clients. Backend services (`lobby`, `gamemaster`, `chat`) communicate via internal Kubernetes DNS (`http://<service-name>.<namespace>.svc.cluster.local:<port>`). Redis is never exposed outside the cluster.
5. **ARM64 Compatibility:** All Dockerfiles must be lightweight (Alpine or slim Debian) and build cleanly on `linux/arm64`. Memory limits must not exceed **160 MiB** per backend container.
6. **No Business Logic State in Container Memory:** All application microservices must be stateless. Persistent state is stored in Redis via the `StateStore` interface.
7. **Player Capacity:** The game strictly supports **4 to 6 players**. The lobby must not start with < 4 players and must reject joins when count reaches 6.

---

## 3. Directory Structure & File Ownership

Do NOT create ad-hoc files in random folders. Adhere strictly to the monorepo structure:

```text
werewolf-sds/
├── services/
│   ├── gateway/                  # Owned by Role 2
│   ├── frontend/                 # Owned by Role 2
│   ├── lobby/                    # Owned by Role 3
│   ├── gamemaster/               # Owned by Role 4
│   └── chat/                     # Owned by Role 5
├── common/                       # Owned by Role 5 (Consumed by Roles 2, 3, 4, 5)
│   ├── state_store.py
│   ├── schemas.py
│   └── trace.py
├── contracts/                    # FROZEN - Single Source of Truth
│   ├── api-contract.md
│   └── internal-room-state.schema.json
├── k8s/                          # Owned by Role 1 (Manifests)
├── scripts/                      # Owned by Role 1 (deploy.sh, pre-pull.sh, build-images.sh)
├── tests/
│   ├── mocks/                    # Owned by Role 5 (mock_gamemaster.py, mock_backend.py)
│   ├── unit/                     # Respective service owners
│   ├── contract/                 # Role 5 & Role 2
│   ├── integration/              # Role 5
│   └── fault/                    # Role 1
├── docker-compose.dev.yml        # Owned by Role 5
└── README.md                     # Owned by Role 1
```

---

## 4. Role Navigation Index

Direct your AI assistant to the appropriate role document based on the task:

| Role Number | Focus Area | Detailed Guide |
|---|---|---|
| **Role 1** | Platform, K3s, Flannel CNI, MetalLB, K8s Manifests, Deployment Scripts | [01-role-infra-k8s.md](01-role-infra-k8s.md) |
| **Role 2** | Gateway Reverse Proxy, Downward API Trace, React Frontend UI & Polling | [02-role-gateway-frontend.md](02-role-gateway-frontend.md) |
| **Role 3** | Lobby Service, Room Codes, Token Session Auth, Pre-Game Lifecycle | [03-role-lobby.md](03-role-lobby.md) |
| **Role 4** | GameMaster Service, Rule Engine, FSM Transitions, PlayerView Sanitization | [04-role-gamemaster.md](04-role-gamemaster.md) |
| **Role 5** | Chat Service, Shared `StateStore` Layer, Redis CAS, Docker Compose & QA | [05-role-chat-statestore-qa.md](05-role-chat-statestore-qa.md) |
