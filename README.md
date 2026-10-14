# Multiplayer Werewolf on Kubernetes (Raspberry Pi Cluster)

> **2110415 Software-Defined Systems — Final Project (Semester 1/2026)**  
> **Team Members:**  
> - Nantaporn Phuaphanbun  
> - Chayut Archamongkol  
> - Chanatda Konchom  
> - Khanapong Kamchoom  
> - Thanyaporn Rattanacharoentham  
>  
> **Submission Deadline:** November 16, 2026 at 23:59 (MCV)  
> **On-Site Demo:** November 17, 2026, 13:00–16:00  

---

## 1. Executive Summary & Project Objectives

This project implements a web-based **Multiplayer Werewolf Game (4–6 players)** deployed on an on-premises Bare-Metal Kubernetes cluster composed of **5 Raspberry Pi 3 B+ nodes** and **1 Notebook VM (Ubuntu Linux)** acting as the Control-Plane / Master node.

### Rubric Mapping & Verification Matrix

The architecture strictly fulfills all requirements set forth in the course specification:

| Evaluation Criteria (Course Rubric) | Implementation & Proof in this Project | Verification Command / Evidence |
|---|---|---|
| **Kube cluster up & running with Pi nodes + Notebook Master** | 1 Ubuntu VM (Notebook) as K3s Master (≥ 2 vCPUs, Bridged Network) + 5 Raspberry Pi 3 B+ as K3s Workers connected via LAN. | `kubectl get nodes -o wide` shows 1 Master and 5 Ready Pi Workers. |
| **Automated Deployment** | Single-script deployment from repository covering namespace, storage, configs, and application workloads. | `./scripts/deploy.sh` executes end-to-end rollout. |
| **App consists of 4–5 distinct container images** | Exactly **5 custom application images** providing dedicated microservices (`gateway`, `frontend`, `lobby`, `gamemaster`, `chat`) + 1 official `redis` infrastructure image. | `kubectl get pods -o custom-columns=NAME:.metadata.name,IMAGE:.spec.containers[*].image` |
| **Logical design of microservices** | Microservices are partitioned by operational domain and failure isolation (Gateway handles routing/trace, Frontend serves static UI, Lobby manages pre-game lifecycle, GameMaster enforces rules/state machine, Chat manages role-based communications, Redis manages shared state). | See [01-architecture-infra.md](docs/01-architecture-infra.md). |
| **Each client request touches ≥ 2 containers** | All external HTTP traffic enters through `gateway`, which reverse-proxies to the respective handler container (`frontend`, `lobby`, `gamemaster`, or `chat`). Internal services are never exposed directly. | Live System Trace Panel on Web UI & `trace` array in HTTP JSON responses. |
| **Containers servicing request are on different nodes** | Enforced via Kubernetes **Hard Pod Anti-Affinity** between `gateway` and all `handler` pods. | Trace data: `trace[0].node != trace[1].node` cross-referenced with `kubectl get pods -o wide`. |
| **All containers used across all services** | A full gameplay loop (Create Room → Join → Start → Night Actions → Day Chat/Vote → End) actively exercises all 5 application containers and Redis. | Demonstrated live via mobile browser clients during demo. |
| **Fault-Tolerance: Pull random Pi offline** | When any Pi running an application pod is disconnected, Kubernetes detects node failure and schedules replacement pods onto surviving nodes. Game state is preserved in Redis on Master; client requests succeed once replacements become Ready. | Pull LAN cable from Pi -> `kubectl get pods -o wide -w` -> Replacement pod Ready -> Client retry succeeds. |

---

## 2. Prerequisites & Equipment Checklist

### 2.1 Hardware
- **1x Ethernet/WiFi Router:** TP-Link TL-WR841N (provided in course kit, configured for wired LAN).
- **5x Raspberry Pi Kits:** Raspberry Pi 3 B+ with power adapters, micro SD cards (16GB+ Class 10), and Ethernet cables.
- **1x Student Notebook:** Running hypervisor (VirtualBox, VMware, or UTM) with an Ubuntu Linux 64-bit VM allocated at least 2 vCPUs and 2 GB RAM.
- **Wired Connectivity:** All 5 Pis and the Notebook must be plugged directly into the TP-Link LAN ports.

### 2.2 Network & IP Plan (Example Subnet `192.168.1.0/24`)
- **Router Gateway:** `192.168.1.1`
- **Master Node (Notebook VM - Bridged Adapter):** `192.168.1.100` (Static DHCP Lease)
- **Worker Nodes (Pi 1 to 5):** `192.168.1.101` – `192.168.1.105`
- **MetalLB VIP Pool:** `192.168.1.240 – 192.168.1.250` (Outside DHCP lease range)
- **Game Access URL:** `http://192.168.1.240` (Assigned to `gateway-service`)

> [!IMPORTANT]
> The Notebook VM network adapter **MUST be set to Bridged Mode** (bound to the physical Ethernet port) so that it shares the exact same broadcast domain as the Raspberry Pis. NAT mode will prevent Pis from joining the K3s cluster.

---

## 3. Cluster Setup Instructions

### 3.1 Prepare Raspberry Pi Worker Nodes
1. Flash **Raspberry Pi OS Lite 64-bit** (Debian Bookworm) or **Ubuntu Server 22.04 LTS 64-bit** onto the 5 micro SD cards.
2. Enable SSH and configure standard credentials across all Pis (e.g., user `pi` / hostname `pi-01` to `pi-05`).
3. Enable Linux cgroups on all Pis by appending the following flags to `/boot/firmware/cmdline.txt` (or `/boot/cmdline.txt`):
   ```text
   cgroup_enable=cpuset cgroup_memory=1 cgroup_enable=memory
   ```
4. Reboot Pis and confirm network reachability via ping from the notebook VM.

### 3.2 Install K3s Control-Plane (on Notebook VM)
On the Ubuntu VM, install K3s Server with default ServiceLB disabled (to use MetalLB) and Flannel CNI enabled:

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable servicelb --flannel-backend=vxlan" sh -

# Verify master status
sudo kubectl get nodes

# Retrieve node join token
sudo cat /var/lib/rancher/k3s/server/node-token
```

### 3.3 Join Raspberry Pi Workers to Cluster
SSH into each Raspberry Pi (`pi-01` through `pi-05`) and run the K3s agent join command:

```bash
curl -sfL https://get.k3s.io | K3S_URL=https://192.168.1.100:6443 \
  K3S_TOKEN="<NODE_TOKEN_FROM_MASTER>" sh -
```

Back on the Notebook VM, label the nodes appropriately:
```bash
kubectl label node <master-hostname> node-role=control-plane
kubectl label node pi-01 pi-02 pi-03 pi-04 pi-05 node-role=pi
kubectl get nodes -o wide
```

### 3.4 Install MetalLB (Bare-Metal Load Balancer)
Install MetalLB via official manifests and apply IP Address Pool configuration:

```bash
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.13.12/config/manifests/metallb-native.yaml

# Wait for MetalLB controller & speakers to be ready
kubectl rollout status -n metallb-system deployment/controller

# Apply Layer-2 IP Pool
kubectl apply -f k8s/metallb-config.yaml
```

---

## 4. Automated Application Deployment

To fulfill the rubric requirement of **Automated Deployment**, the entire application lifecycle is automated via repository scripts.

### 4.1 Build and Pre-pull Images (ARM64 Optimization)
Because the Raspberry Pi 3 B+ has constrained memory (1GB RAM) and limited network bandwidth during on-site grading:
1. Build Multi-Arch ARM64 images on the notebook:
   ```bash
   ./scripts/build-images.sh
   ./scripts/push-images.sh
   ```
2. Pre-pull all images onto all 5 Raspberry Pis before demo evaluation to eliminate image download delays during fault-tolerance testing:
   ```bash
   ./scripts/pre-pull.sh
   ```

### 4.2 One-Command Deployment
Run the automated deployment script on the Master VM:
```bash
./scripts/deploy.sh
```

This script automatically executes:
1. Creates namespace `werewolf`.
2. Deploys `redis` with PersistentVolume pinned strictly to the Control-Plane node.
3. Deploys `gateway` with Hard Pod Anti-Affinity against handlers.
4. Deploys handler microservices (`frontend`, `lobby`, `gamemaster`, `chat`) distributed across Pi workers.
5. Deploys Kubernetes `ClusterIP` and MetalLB `LoadBalancer` services.
6. Waits for all readiness probes to pass.

Verify deployment:
```bash
kubectl get pods -n werewolf -o wide
kubectl get svc -n werewolf -o wide
```

---

## 5. Live Demo Guide & Cross-Node Trace Validation

### 5.1 Accessing the Application
Open any web browser (desktop or mobile connected to the TP-Link Wi-Fi/LAN) and navigate to the MetalLB LoadBalancer VIP:
```text
http://192.168.1.240
```

### 5.2 Playing the Game (5-Player Demo Flow)
1. **Create Room:** Host (Member 1) opens `http://192.168.1.240`, enters their name, and clicks **Create Room**. A 4-character Room Code (e.g., `WOLF`) is issued.
2. **Join Room:** Members 2–5 enter the Room Code and their respective names.
3. **Start Game:** Once 5 players are in the lobby, the **Start Game** button becomes active for the Host. Click to assign secret roles:
   - 1x Werewolf, 1x Doctor, 1x Seer, 2x Villagers.
4. **Night Phase (45s):**
   - Werewolf selects a target to eliminate (WOLF chat channel accessible).
   - Doctor selects a target to protect.
   - Seer selects a player to inspect alignment (`WEREWOLF` vs `GOOD`).
   - Villagers wait.
5. **Day Phase (60s):**
   - Night casualties announced.
   - Public chat discussion active.
   - Players cast votes to execute a suspect or choose `SKIP`.
6. **Game Conclusion:** Loop proceeds until all wolves are eliminated (Villagers Win) or wolves equal/outnumber good players (Werewolves Win).

### 5.3 Proving Cross-Node Request Servicing (SDN Requirement)
Every HTTP response carries a structured `trace` envelope injected by containers via the Kubernetes Downward API (`POD_NAME`, `NODE_NAME`):

```json
{
  "ok": true,
  "data": { "room_id": "WOLF" },
  "request_id": "req-9c8e1a",
  "trace": [
    { "service": "gateway", "pod": "gateway-6b7c-8j2k", "node": "pi-01" },
    { "service": "lobby",   "pod": "lobby-5d8f-m4xq",   "node": "pi-03" }
  ]
}
```

- **Visual Debug Panel:** A collapsible HUD on the frontend displays the real-time execution path for every user interaction (`gateway (pi-01) -> gamemaster (pi-04)`).
- **Verification:** Cross-check the nodes reported in the HUD against `kubectl get pods -n werewolf -o wide` to prove that the request was processed by ≥ 2 containers residing on physically distinct hardware nodes.

---

## 6. Fault-Tolerance Demo Guide (Pulling a Pi Offline)

The grading rubric requires randomly taking one Raspberry Pi offline and demonstrating that the application self-heals and continues to serve requests.

### Execution Steps
1. Identify the pods running on each Pi:
   ```bash
   kubectl get pods -n werewolf -o wide
   ```
2. Start streaming cluster events and pod status in a terminal:
   ```bash
   kubectl get pods -n werewolf -o wide -w
   ```
3. **Pull the Failure Trigger:** Have the instructor randomly pick a Raspberry Pi (e.g., `pi-02` running `gamemaster`) and physically disconnect its Ethernet cable (or pull the power plug).
4. **Observe Self-Healing:**
   - K3s marks `pi-02` as `NotReady`.
   - Kubernetes detects pod unavailability and evicts the failed pod.
   - Kubernetes ReplicaSet automatically schedules a **Replacement Pod** onto an active surviving Pi node.
   - The Replacement Pod starts, loads its container image (instantly via pre-pull cache), and passes its HTTP `readinessProbe`.
5. **Verify Request Success & State Preservation:**
   - From the mobile browser, perform an action or refresh state.
   - **Result:** The request succeeds. The game resumes in the exact same phase, with identical player roles, votes, and chat history intact.
   - **Trace Proof:** The System Trace Panel on the browser will update to reflect the newly scheduled pod and its new node host (e.g., `gamemaster-new (pi-04)`).

---

## 7. Known Architectural Limitations

As per standard engineering practice, the following trade-offs and design constraints are acknowledged:
1. **Single-Instance Redis on Master:** Redis runs as a single instance pinned to the Notebook Control-Plane VM with a PersistentVolume. While the system provides complete fault-tolerance against any Raspberry Pi worker failure (matching the project specification), failure of the student notebook itself is not highly available.
2. **REST Polling vs WebSocket:** State synchronization is maintained via client-side REST polling (2-second interval) rather than persistent WebSockets. This deliberate choice avoids half-open TCP socket deadlocks during node failure events and guarantees deterministic recovery after pod migration.
3. **Player Session Scope:** Sessions are managed per-room via cryptographically random Bearer tokens; full multi-tenant user account registration is out of scope.

---

## 8. Reset & Teardown Instructions

After grading is completed:
1. **Teardown Cluster & Manifests:**
   ```bash
   ./scripts/reset-demo.sh
   ```
2. **Restore Hardware (as required by rubric):**
   - Re-flash all 5 Raspberry Pi micro SD cards with clean default Raspberry Pi OS.
   - Factory reset the TP-Link TL-WR841N wireless router by holding the physical reset button for 10 seconds.
   - Return all hardware kits, power adapters, and Ethernet cables to the instructor.
