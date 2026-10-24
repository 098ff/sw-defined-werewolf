# AI Agent Guide — Role 1: Platform & Infrastructure Lead

> **Role Focus:** Kubernetes (K3s), Flannel CNI, MetalLB L2, K8s Manifests, Resource Limits, and Automation Scripts.  
> **Master Context:** Read [00-agent-system-prompt.md](00-agent-system-prompt.md) and [01-architecture-infra.md](../01-architecture-infra.md) first.

---

## 1. Role Scope & Owned Files

As the Infrastructure Lead agent, your primary objective is to deliver a reliable, automated Kubernetes environment that enforces cross-node request scheduling and fault recovery on Raspberry Pi 3 B+ hardware.

### Files You Own
- `k8s/*.yaml` (All Kubernetes manifests: namespace, redis, gateway, frontend, lobby, gamemaster, chat, services, metallb)
- `scripts/*.sh` (`install-master.sh`, `join-workers.sh`, `build-images.sh`, `push-images.sh`, `pre-pull.sh`, `deploy.sh`, `reset-demo.sh`, `fault-test.sh`)
- `README.md` (Maintain instructions and verify command accuracy)
- `tests/fault/*` (Node failure verification scripts)

### Files You Must NOT Modify
- Do not edit application business logic inside `services/lobby/`, `services/gamemaster/`, `services/chat/`.
- Do not modify API contracts in `contracts/api-contract.md`.

---

## 2. Infrastructure Specifications & Invariants

1. **Control-Plane Node:** The Master runs K3s server on the Notebook Ubuntu VM (Bridged Network Adapter, IP `192.168.0.100`).
2. **Worker Nodes:** 5x Raspberry Pi 3 B+ (Hostnames `pi-01` to `pi-05`, IPs `192.168.0.101`–`105`).
3. **CNI:** Built-in K3s **Flannel** (`--flannel-backend=vxlan`). Do not install external CNIs unless explicitly required.
4. **LoadBalancer:** **MetalLB** in Layer-2 mode. Subnet pool `192.168.0.240-192.168.0.250`. Disables K3s `servicelb` (`--disable servicelb`).
5. **Node Labels:**
   - Master: `node-role=control-plane`
   - Pis: `node-role=pi`
6. **Hard Pod Anti-Affinity Rule (Crucial for Grade):**
   - The `gateway` Deployment must have `requiredDuringSchedulingIgnoredDuringExecution` against any pod with label `component=handler`.
   - All backend handlers (`frontend`, `lobby`, `gamemaster`, `chat`) must carry label `component: handler`.
   - `gateway` must have fallback tolerance to schedule on `control-plane` if all remaining active Pis are populated with handlers.
7. **Redis Pinning:**
   - Redis must use `nodeSelector: { node-role: control-plane }` and tolerations for master taints. It must mount a `hostPath` PersistentVolume at `/var/lib/werewolf-redis`.
8. **Resource Ceilings (1GB RAM per Pi):**
   - Memory requests: `64MiB`, Memory limits: `160MiB` per backend container.
   - Nginx frontend: `16MiB` request, `64MiB` limit.
   - All containers must configure HTTP `readinessProbe` and `livenessProbe` on path `/health/ready` and `/health/live`.

---

## 3. Local Development & Testing Instructions

You do not need physical Raspberry Pis to develop and validate manifests! You can test scheduling, anti-affinity, and failure behavior locally.

### 3.1 Local Test Setup with `k3d`
Simulate the 1-master + 5-worker topology locally on your machine:
```bash
# Create multi-node local cluster
k3d cluster create werewolf-local \
  --servers 1 \
  --agents 5 \
  --port "8080:80@loadbalancer"

# Label nodes to match physical production
kubectl label node k3d-werewolf-local-server-0 node-role=control-plane
kubectl label node k3d-werewolf-local-agent-0 k3d-werewolf-local-agent-1 k3d-werewolf-local-agent-2 k3d-werewolf-local-agent-3 k3d-werewolf-local-agent-4 node-role=pi
```

### 3.2 Testing Anti-Affinity & Placement
Apply placeholder mock deployments to verify that Kubernetes schedules Gateway and Handlers onto separate nodes:
```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/
kubectl get pods -n werewolf -o wide
```
Confirm:
- `gateway` pod is NOT on the same node as any `frontend`, `lobby`, `gamemaster`, or `chat` pod.
- `redis` pod is exclusively on the control-plane node.

### 3.3 Testing Node Failure & Recovery
```bash
# Simulate pulling a worker offline
docker stop k3d-werewolf-local-agent-1

# Monitor pod eviction and replacement
kubectl get nodes
kubectl get pods -n werewolf -o wide -w
```
Confirm that K3s creates replacement pods on the surviving agent nodes within the configured toleration window (`10s`).

---

## 4. Key Manifest Templates

### 4.1 Pod Anti-Affinity Block (`k8s/gateway.yaml`)
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gateway
  namespace: werewolf
spec:
  replicas: 1
  selector:
    matchLabels:
      app: gateway
  template:
    metadata:
      labels:
        app: gateway
        component: ingress
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: component
                operator: In
                values: ["handler"]
            topologyKey: "kubernetes.io/hostname"
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            preference:
              matchExpressions:
              - key: node-role
                operator: In
                values: ["pi"]
      tolerations:
      - key: "node.kubernetes.io/unreachable"
        operator: "Exists"
        effect: "NoExecute"
        tolerationSeconds: 10
      - key: "node.kubernetes.io/not-ready"
        operator: "Exists"
        effect: "NoExecute"
        tolerationSeconds: 10
      containers:
      - name: gateway
        image: werewolf/gateway:v1.0
        env:
        - name: POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: NODE_NAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
        resources:
          requests:
            memory: "64Mi"
            cpu: "50m"
          limits:
            memory: "160Mi"
            cpu: "200m"
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8000
          initialDelaySeconds: 3
          periodSeconds: 3
```

---

## 5. Ready-to-Use Agent Prompt

Copy and paste this prompt when initiating tasks with your AI assistant:
```text
You are acting as the Infrastructure & Platform Engineer (Role 1) for the Werewolf SDS project.
Your task is to write/debug Kubernetes manifests in /k8s and shell automation scripts in /scripts.
Strictly adhere to docs/roles/01-role-infra-k8s.md and docs/roles/00-agent-system-prompt.md.
Make sure every deployment sets Downward API env vars (POD_NAME, NODE_NAME), memory limits <= 160MiB,
readiness probes, and proper Pod Anti-Affinity.
```

---

## 6. Service Integration Checklist (TODO-01)

Search tag: `TODO-01` across the repository to locate all cross-service integration touchpoints.
When teammates finish their microservices and prepare to integrate on Kubernetes, Chanatda Konchom (Role 1) must verify this checklist:

### [TODO-01-A] Integration with Khanapong Kamchoom (Role 2: Gateway & Frontend)
- [ ] **Gateway Upstream URLs:** Verify that `gateway` reads internal service URLs from environment variables matching `k8s/gateway.yaml`:
  - `LOBBY_URL=http://lobby:8000`
  - `GAMEMASTER_URL=http://gamemaster:8000`
  - `CHAT_URL=http://chat:8000`
  - `FRONTEND_URL=http://frontend:80`
- [ ] **Trace Propagation & Downward API:** Verify that `gateway` generates `X-Request-ID`, reads `POD_NAME` & `NODE_NAME` via Downward API, prepends its hop, and collects upstream backend trace entries.
- [ ] **Frontend Routing & Health Probes:** Confirm `frontend` Nginx listens on port `80`, serves static React build, and responds with HTTP 200 on `/health/ready` and `/health/live`.
- [ ] **UI Trace HUD:** Verify that the frontend UI contains the collapsible System Trace HUD displaying `gateway (node) -> handler (node)` for the on-site grading demo.
- [ ] **ARM64 Dockerfile:** Confirm both `services/gateway/Dockerfile` and `services/frontend/Dockerfile` build cleanly on `linux/arm64`.

### [TODO-01-B] Integration with Thanyaporn Rattanacharoentham (Role 3: Lobby Service)
- [ ] **Lobby Port & Endpoints:** Verify that `lobby` container exposes port `8000` and serves `/health/ready` and `/health/live` returning HTTP 200.
- [ ] **Environment Variables:** Confirm `lobby` handles `REDIS_URL=redis://redis:6379`, `STATE_STORE_BACKEND=redis`, and `GAMEMASTER_URL=http://gamemaster:8000`.
- [ ] **Downward API Trace:** Verify `lobby` reads `os.getenv("POD_NAME")` and `os.getenv("NODE_NAME")` and returns them in the response envelope trace array.
- [ ] **Memory Limit Compliance:** Confirm that running Lobby under load consumes $< 160\text{ MiB}$ RAM to avoid OOM panics on the 1GB Raspberry Pis.

### [TODO-01-C] Integration with Nantaporn Phuaphanbun (Role 4: GameMaster Service)
- [ ] **GameMaster Port & Endpoints:** Verify that `gamemaster` container exposes port `8000` and serves `/health/ready` and `/health/live` returning HTTP 200.
- [ ] **Environment Variables:** Confirm `gamemaster` handles `REDIS_URL=redis://redis:6379` and `STATE_STORE_BACKEND=redis`.
- [ ] **Redis TIME Authority:** Confirm GameMaster calculates phase durations (`45s` night, `60s` day) strictly using Redis `TIME` (avoiding host node clock drift among the 5 Pis).
- [ ] **Memory Limit Compliance:** Confirm that rule evaluation and state serialization stay well under $160\text{ MiB}$ RAM.

### [TODO-01-D] Integration with Chayut Archamongkol (Role 5: Chat, StateStore & Docker Compose / QA)
- [ ] **Chat Port & Endpoints:** Verify that `chat` container exposes port `8000` and serves `/health/ready` and `/health/live` returning HTTP 200.
- [ ] **Redis Data Persistence & Volume:** Confirm that Redis data directory `/data` persists to `/var/lib/werewolf-redis` on the Control-Plane Master VM.
- [ ] **Docker Compose vs K8s Parity:** Cross-check environment variable names between `docker-compose.dev.yml` and `k8s/*.yaml` to prevent divergence.
- [ ] **Pre-Demo State Flush:** Coordinate on `./scripts/reset-demo.sh` to ensure Redis FLUSHALL cleanly resets state between test iterations without breaking active pods.

