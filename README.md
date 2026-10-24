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
- **1x Student Notebook:** Running hypervisor (VirtualBox on macOS/Windows/Linux) with an Ubuntu Linux VM allocated at least 2 vCPUs and 2 GB RAM.  
  👉 **Detailed VM Guide for macOS / VirtualBox:** [docs/04-virtualbox-master-setup.md](docs/04-virtualbox-master-setup.md)
- **Wired Connectivity:** All 5 Pis and the Notebook must be plugged directly into the TP-Link LAN ports.

### 2.2 Network & IP Plan (Example Subnet `192.168.0.0/24`)
- **Router Gateway:** `192.168.0.1`
- **Master Node (Notebook VM - Dual NIC):**
  - **Adapter 1 (Bridged to Ethernet LAN):** `192.168.0.100` (Static IP for K3s Master)
  - **Adapter 2 (NAT to Host Wi-Fi):** Outbound internet access for downloading packages
- **Worker Nodes (Pi 1 to 5):** `192.168.0.101` – `192.168.0.105`
- **MetalLB VIP Pool:** `192.168.0.240 – 192.168.0.250` (Outside DHCP lease range)
- **Game Access URL:** `http://192.168.0.240` (Assigned to `gateway-service`)

> [!IMPORTANT]
> The Notebook VM Adapter 1 **MUST be set to Bridged Mode** (bound to the physical Ethernet port) with **Promiscuous Mode = Allow All** so that it shares the exact same broadcast domain as the Raspberry Pis and allows Flannel VXLAN packets to traverse the bridge. Adapter 2 (NAT) provides outbound internet access. Detailed instructions: [docs/04-virtualbox-master-setup.md](docs/04-virtualbox-master-setup.md).

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
On the Ubuntu VM, execute our turnkey master installation script:

```bash
# Automated 1-step master setup (disables servicelb, enables Flannel VXLAN, binds 192.168.0.100)
./scripts/install-master.sh
```

The script will configure kernel parameters, disable swap, install K3s, label the master node (`node-role=control-plane`), prepare `/var/lib/werewolf-redis`, and output the node join token.

### 3.3 Join Raspberry Pi Workers to Cluster
From the Master VM, run the automated worker join script:

```bash
./scripts/join-workers.sh
```

Or run the join command directly on each Raspberry Pi (`pi-01` through `pi-05`):
```bash
curl -sfL https://get.k3s.io | sudo INSTALL_K3S_VERSION="v1.28.8+k3s1" \
  K3S_URL=https://192.168.0.100:6443 \
  K3S_TOKEN="<NODE_TOKEN_FROM_MASTER>" sh -
```

Verify that all 5 workers are joined and labeled:
```bash
kubectl get nodes -o wide --show-labels
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
1. **Build Multi-Arch ARM64 images:**
   ```bash
   ./scripts/build-images.sh
   ```
2. **Push or Export Images:**
   - **Online (Registry):**
     ```bash
     ./scripts/push-images.sh
     ```
   - **Offline Mode (For lab demos without internet connection):**
     ```bash
     # Save all 5 images to compressed tarball
     ./scripts/push-images.sh --save-tar
     ```
3. **Pre-load images onto all 5 Raspberry Pis:**
   - **Online Pre-pull:**
     ```bash
     ./scripts/pre-pull.sh
     ```
   - **Offline Pre-load:**
     ```bash
     ./scripts/pre-pull.sh --import-tar werewolf-images.tar.gz
     ```

### 4.2 One-Command Deployment
Run the automated deployment script on the Master VM:
```bash
./scripts/deploy.sh
```

This script automatically executes:
1. Verifies cluster connectivity and ready nodes.
2. Creates namespace `werewolf`.
3. Deploys `redis` with PersistentVolume pinned strictly to the Control-Plane node.
4. Deploys `gateway` with Hard Pod Anti-Affinity against handlers and master-fallback tolerations.
5. Deploys handler microservices (`frontend`, `lobby`, `gamemaster`, `chat`) distributed across Pi workers.
6. Deploys MetalLB Layer-2 LoadBalancer service (`http://192.168.0.240`).
7. Waits for all readiness and liveness probes to pass.
8. Displays instant SDN cross-node scheduling verification.

Verify deployment:
```bash
kubectl get pods -n werewolf -o wide
kubectl get svc -n werewolf -o wide
python3 tests/fault/verify_topology.py
```

### 4.3 Independent Local Verification (Before Hardware Assembly)
Developers and evaluators can verify the entire Kubernetes topology locally without physical Raspberry Pis:

```bash
# 1. Run static manifest compliance lint tests (zero external dependencies)
python3 -m unittest tests/unit/test_manifest_compliance.py

# 2. (Optional) Create local 1-Master + 5-Worker cluster via k3d
./scripts/local-cluster.sh up

# 3. Build native images and deploy locally
./scripts/build-images.sh --local
./scripts/deploy.sh

# 4. Verify topology & cross-node placement
python3 tests/fault/verify_topology.py
```

### 4.4 Application Test Suite (Unit + End-to-End)
Unit tests cover every service and both StateStore backends (in-memory and Redis via fakeredis), so no running Redis is needed:

```bash
pip install -r requirements-dev.txt
python3 -m pytest -q
```

The E2E script plays a full 5-player game through the gateway and asserts the standard envelope, chat channel permissions, role hiding and that every request touches >= 2 containers:

```bash
./scripts/local-dev.sh up
python3 tests/e2e/run_game_flow.py                              # docker compose (http://localhost:8080)
python3 tests/e2e/run_game_flow.py --base-url http://192.168.0.240   # K3s cluster via MetalLB
```

---

## 5. Live Demo Guide & Cross-Node Trace Validation

### 5.1 Accessing the Application
Open any web browser (desktop or mobile connected to the TP-Link Wi-Fi/LAN) and navigate to the MetalLB LoadBalancer VIP:
```text
http://192.168.0.240
```

### 5.2 Playing the Game (5-Player Demo Flow)
1. **Create Room:** Host (Member 1) opens `http://192.168.0.240`, enters their name, and clicks **Create Room**. A 4-character Room Code (e.g., `WOLF`) is issued.
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
   python3 tests/fault/verify_topology.py
   ```
2. Run the automated fault test monitor:
   ```bash
   ./tests/fault/test_fault_recovery.sh
   # Or run live watch:
   # ./scripts/fault-test.sh
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
