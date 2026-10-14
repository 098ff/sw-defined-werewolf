# Team Workflow, Division of Labor & Testing Strategy

> **Target Audience:** All Team Members (Members 1 to 5)  
> **Related Files:** [README.md](../README.md), [01-architecture-infra.md](01-architecture-infra.md), [api-contract.md](../contracts/api-contract.md)

---

## 1. Repository Structure

The project is structured as a single Monorepo to facilitate schema sharing, Docker multi-arch building, and integration testing:

```text
werewolf-sds/
├── services/
│   ├── gateway/                  # Member 2: Reverse Proxy & Trace Generator
│   │   ├── app/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── frontend/                 # Member 2: React SPA + Nginx
│   │   ├── src/
│   │   ├── nginx.conf.template
│   │   └── Dockerfile
│   ├── lobby/                    # Member 3: Room Management & Token Auth
│   │   ├── app/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── gamemaster/               # Member 4: State Machine & Rules Authority
│   │   ├── app/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   └── chat/                     # Member 5: Message Streams & Permissions
│       ├── app/
│       ├── Dockerfile
│       └── requirements.txt
├── common/                       # Shared modules across services
│   ├── state_store.py            # Member 5: StateStore Interface & Redis/Memory implementations
│   ├── schemas.py                # Shared Pydantic data schemas
│   └── trace.py                  # Downward API trace reader helper
├── contracts/                    # Absolute Schema & API Specifications
│   ├── api-contract.md
│   └── internal-room-state.schema.json
├── k8s/                          # Member 1: Kubernetes Manifests
│   ├── namespace.yaml
│   ├── redis.yaml
│   ├── gateway.yaml
│   ├── frontend.yaml
│   ├── lobby.yaml
│   ├── gamemaster.yaml
│   ├── chat.yaml
│   ├── services.yaml
│   └── metallb-config.yaml
├── scripts/                      # Automated Deployment & Operations
│   ├── install-master.sh
│   ├── join-workers.sh
│   ├── build-images.sh
│   ├── push-images.sh
│   ├── pre-pull.sh
│   ├── deploy.sh
│   ├── reset-demo.sh
│   └── fault-test.sh
├── tests/
│   ├── unit/                     # Isolated service unit tests
│   ├── contract/                 # Schema & API envelope validation
│   ├── integration/              # Multi-container Redis integration tests
│   └── fault/                    # Node failure recovery tests
├── docker-compose.dev.yml        # Local multi-service testing stack
├── .env.example
└── README.md
```

---

## 2. Division of Labor (5 Members)

To maximize autonomy and eliminate blocking dependencies, each member owns specific deliverables and isolated test harnesses:

| Member | Primary Role | Core Deliverables | Independent Local Testing Mode |
|:---:|---|---|---|
| **Member 1** | **Platform / Infra Lead** | Ubuntu VM Master, K3s installation scripts, Flannel CNI, MetalLB VIP config, K8s manifests (Anti-Affinity, tolerations, resource limits), `deploy.sh`, `pre-pull.sh`. | Uses local K3d/Kind cluster on laptop to test manifests and scheduling before deploying to Pi hardware. |
| **Member 2** | **Gateway & Frontend Lead** | FastAPI gateway reverse proxy, Downward API `trace` injector, React UI components (Lobby, Night/Day HUD, Chat, Trace HUD), Nginx Dockerfile. | Runs Gateway + Frontend against mock backend endpoints returning canned JSON fixtures. |
| **Member 3** | **Lobby Service Lead** | Room creation (unique code generator), player join, room capacity enforcement, Player Session token issuance, handoff to GameMaster. | Tests via FastAPI Swagger UI (`/docs`) using `InMemoryStateStore`. Zero Redis or K8s dependency. |
| **Member 4** | **GameMaster Service Lead** | Deterministic role assignment (4–6 players), Night action resolution, Day vote tally algorithm, win conditions, sanitized `PlayerView` generator. | Pure Python unit tests (`pytest tests/unit/test_gamemaster.py`) covering all game rules and edge cases. |
| **Member 5** | **Chat, StateStore & QA Lead** | `StateStore` interface (`InMemoryStateStore` & `RedisStateStore` with CAS `WATCH/MULTI/EXEC`), Chat channel authorization (`PUBLIC`, `WOLF`, `DEAD`), Docker Compose setup. | Tests Redis data layer and Chat permissions locally using `docker-compose.dev.yml`. |

### Decoupling Rules (Day 1 Execution)
1. **Day 1 Contract Freeze:** Member 5 delivers `common/state_store.py` interface stubs. Members 3, 4, and 5 program against this interface without waiting for Redis.
2. **Mock Payloads:** Member 2 builds the frontend against the contracts defined in [api-contract.md](../contracts/api-contract.md) without waiting for backend implementations.
3. **Skeleton Images:** Member 1 tests cluster networking and pod anti-affinity using lightweight placeholder Nginx containers prior to receiving finished service code.

---

## 3. Local Development Environments & Isolated Testing

To ensure zero friction and prevent blocking dependencies, developers can test in two distinct modes.

### 3.1 Service-Isolated Mode (Single Developer / Fast Dev Loop)
In this mode, you do not need Redis, Docker, Kubernetes, or other finished microservices.

1. **In-Memory StateStore:** Set `STATE_STORE_BACKEND=in_memory` so your service stores state in RAM.
2. **Upstream Mocks (`tests/mocks/`):**
   - If developing **Lobby**, run the GameMaster mock in a separate terminal:
     ```bash
     python tests/mocks/mock_gamemaster.py --port 8002
     ```
     Set `GAMEMASTER_URL=http://localhost:8002`. Lobby can test the complete room-start flow without the real GameMaster.
   - If developing **Gateway** or **Frontend**, run the Unified Backend mock:
     ```bash
     python tests/mocks/mock_backend.py --port 8000
     ```
     You can switch scenarios interactively (e.g. `POST /mock/set-scenario?name=night_phase`) to test Seer cards, vote ties, skip majorities, or error screens without playing through the entire game!

#### Step-by-Step Example (Running Lobby Standalone):
```bash
# 1. Move to service directory
cd services/lobby

# 2. Create isolated python virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start Lobby with In-Memory store and point to mock GM
export STATE_STORE_BACKEND=in_memory
export GAMEMASTER_URL=http://localhost:8002
uvicorn app.main:app --reload --port 8001
```
Open your browser at `http://localhost:8001/docs` to test endpoints via Swagger UI.

### 3.2 Full Integration Mode (Docker Compose)
To test the complete 5-service topology + Redis together on a development machine:
```bash
# Start all 5 microservices + Redis in the background
./scripts/local-dev.sh up

# View real-time logs across all services
./scripts/local-dev.sh logs

# Stop and clean up containers
./scripts/local-dev.sh down
```
Open `http://localhost:8080` in your browser. All requests flow through `gateway` and display live Downward API node hops in the System Trace HUD.

---

## 3.3 Automated Operational Scripts (`scripts/`)

To fulfill the rubric requirement (*"Demo automatic deployment of your application with all components available in your Github repo"*), the following executable scripts are provided:

| Script Path | Purpose | When to Use |
|---|---|---|
| `scripts/deploy.sh` | 1-Click Kubernetes deployment of Namespace, Redis, Gateway, and Handlers. | Used during on-site demo evaluation. |
| `scripts/build-images.sh` | Compiles multi-arch ARM64 Docker images for Raspberry Pi 3 B+. | Before pushing images to registry. |
| `scripts/pre-pull.sh` | Pre-pulls images to all 5 Pis via SSH to avoid download delays during demo. | Before starting demo grading. |
| `scripts/reset-demo.sh` | Flushes Redis and restarts pods to reset demo to clean baseline. | Between test runs or after grading. |
| `scripts/fault-test.sh` | Streams pod eviction and replacement events when a Pi is disconnected. | During the fault-tolerance demo. |
| `scripts/local-dev.sh` | Convenience CLI for starting/stopping the local Docker Compose stack. | During local integration testing. |

---

## 4. Testing Strategy

### 4.1 Unit Testing
- **Lobby:** Enforces 4–6 player boundaries, rejects duplicate names, rejects joins after room start.
- **GameMaster:** Exhaustively tests role permutations, doctor saves, seer inspections, vote ties, and skip logic.
- **Chat:** Confirms dead players cannot send public chat; verifies non-wolves cannot access wolf chat.

Run all unit tests:
```bash
pytest tests/unit/
```

### 4.2 Contract Testing
Validates that every service response strictly conforms to the standard response envelope:
- Ensures `ok`, `data`, `request_id`, and `trace` keys exist.
- Validates that HTTP status codes match the contract (`409` for conflicts, `403` for forbidden actions).
```bash
pytest tests/contract/
```

### 4.3 Concurrent Request & StateStore Testing
Ensures Redis optimistic concurrency control (`WATCH/MULTI/EXEC`) prevents race conditions:
- Simulates 5 players submitting votes simultaneously.
- Simulates concurrent chat messages.
- Verifies zero lost updates or corrupted JSON room states.
```bash
pytest tests/integration/test_concurrency.py
```

### 4.4 End-to-End (E2E) Test Scenario
Run before any merge to `main`:
1. Player 1 creates room $\rightarrow$ Receives Host Token.
2. Players 2–5 join room $\rightarrow$ Receive Player Tokens.
3. Host triggers Start $\rightarrow$ GameMaster assigns roles.
4. Verify every player sees their own role and hidden roles for others.
5. Submit Night actions $\rightarrow$ Confirm casualty resolution.
6. Submit Day chat and votes $\rightarrow$ Confirm execution resolution.
7. Verify game concludes when win condition is met.

---

## 5. Risk Register & Mitigation Matrix

| Priority | Risk Event | Impact | Preventive & Contingency Action |
|:---:|---|---|---|
| **CRITICAL** | **VM & Pi Subnet Mismatch** | Pis cannot join cluster or CNI fails. | Configure VM network adapter to **Bridged Mode** bound to physical Ethernet; verify IP allocation and `ping` before installing K3s. |
| **CRITICAL** | **Scheduler Pending on Pi Failure** | Pod replacement cannot be scheduled due to anti-affinity constraints. | Configure `gateway` anti-affinity with fallback tolerance to Control-Plane node if all remaining Pis are saturated with handlers. |
| **HIGH** | **ARM64 Container Incompatibility** | Pod crashloops on Pi 3 B+ (`exec format error`). | Use `docker buildx build --platform linux/arm64` on every image; verify binary architecture before pushing. |
| **HIGH** | **OOM Killed on Pi 3 B+ (1GB RAM)** | Node freezes or kernel panics. | Strict memory limits (`160MiB` max for backend pods); run OS in headless Lite mode; pre-pull images. |
| **HIGH** | **Lost Updates on High-Concurrency Votes** | Desynchronized game state. | Mandatory CAS (`WATCH/MULTI/EXEC`) in `RedisStateStore.update_room()`. |
| **MEDIUM** | **Contract Drift Across Team** | Integration breakage upon merging. | Absolute schema freeze on [api-contract.md](../contracts/api-contract.md); PRs modifying contracts require approval from all service owners. |

---

## 6. Definition of Done (DoD)

A service or feature is considered **Done** and ready for demo grading only when all criteria are satisfied:
- [ ] Code compiles and passes all local Unit and Contract tests.
- [ ] Multi-arch ARM64 Dockerfile builds cleanly without warning.
- [ ] Container reads `POD_NAME` and `NODE_NAME` via Downward API and injects valid trace objects.
- [ ] Memory utilization stays within allocated budget (< 160 MiB under load).
- [ ] Service integrates successfully in `docker-compose.dev.yml` end-to-end loop.
- [ ] Deployment manifest includes configured readiness probes and pod anti-affinity labels.
- [ ] Tested on the physical Raspberry Pi cluster with at least one simulated node failure.
