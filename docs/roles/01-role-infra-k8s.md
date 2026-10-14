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

1. **Control-Plane Node:** The Master runs K3s server on the Notebook Ubuntu VM (Bridged Network Adapter, IP `192.168.1.100`).
2. **Worker Nodes:** 5x Raspberry Pi 3 B+ (Hostnames `pi-01` to `pi-05`, IPs `192.168.1.101`–`105`).
3. **CNI:** Built-in K3s **Flannel** (`--flannel-backend=vxlan`). Do not install external CNIs unless explicitly required.
4. **LoadBalancer:** **MetalLB** in Layer-2 mode. Subnet pool `192.168.1.240-192.168.1.250`. Disables K3s `servicelb` (`--disable servicelb`).
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
