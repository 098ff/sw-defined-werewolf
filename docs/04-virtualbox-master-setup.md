# macOS VirtualBox Ubuntu VM Setup Guide (K3s Control-Plane Master)

> **Audience:** Platform / Infra Lead (Chanatda Konchom), Team Members, Instructors & TAs  
> **Target OS:** Ubuntu Server 22.04 LTS or 24.04 LTS (64-bit ARM64 / AMD64 matching your Mac)  
> **Hypervisor:** Oracle VirtualBox 7.x on macOS  

---

## 1. Overview & Architecture

In this project, your notebook acts as the **K3s Control-Plane (Master Node)**, orchestrating 5 Raspberry Pi 3 B+ worker nodes.

```text
+---------------------------------------------------------------------------------+
| macOS Notebook Host                                                             |
|                                                                                 |
|   [Wi-Fi Adapter: en0] -----> Internet (for apt-get, docker pull, curl)        |
|                                     ^                                           |
|   [VirtualBox VM: sds-k8s-master]   |                                           |
|     - Adapter 2 (NAT) --------------+ (Outbound Internet Access)                |
|     - Adapter 1 (Bridged) ----------+ (Private Cluster Subnet: 192.168.1.100)   |
|                                     |                                           |
|   [USB-C Ethernet Adapter: en5] ----+                                           |
+-------------------------------------+-------------------------------------------+
                                      |
                                      | Cat5e Cable
                                      v
                        [TP-Link TL-WR841N Router]
                          (LAN Subnet: 192.168.1.0/24)
                           /     |      |      |     \
                        pi-01  pi-02  pi-03  pi-04  pi-05
                        .101   .102   .103   .104   .105
```

### Why Dual Adapters (Bridged + NAT)?
- **Adapter 1 (Bridged to USB-C Ethernet):** Puts the Ubuntu VM directly on the `192.168.1.0/24` subnet alongside the Raspberry Pis. The Pis connect directly to K3s port `6443` on `192.168.1.100`.
- **Adapter 2 (NAT to Mac's Wi-Fi):** Provides outgoing internet access to download packages (`curl`, `k3s`, `docker`, `git`) even when the TP-Link router has no internet uplink during offline lab demos.

---

## 2. Choosing the Correct Ubuntu ISO for macOS

Check your Mac architecture by opening Terminal on macOS:
```bash
uname -m
```
- **If output is `arm64` (Apple Silicon M1/M2/M3/M4):**
  Download **Ubuntu Server for ARM64**:
  - Image: `ubuntu-22.04.4-live-server-arm64.iso` or `ubuntu-24.04-live-server-arm64.iso`
- **If output is `x86_64` (Intel Mac):**
  Download **Ubuntu Server for AMD64**:
  - Image: `ubuntu-22.04.4-live-server-amd64.iso` or `ubuntu-24.04-live-server-amd64.iso`

---

## 3. Creating the VM in VirtualBox on macOS

### Step 3.1: Hardware Allocation (Course Rubric Compliant)
1. In VirtualBox, click **New**:
   - **Name:** `sds-k8s-master`
   - **Type:** `Linux`
   - **Version:** `Ubuntu (64-bit)` / `Ubuntu (ARM 64-bit)`
   - **ISO Image:** Select the downloaded Ubuntu Server ISO.
   - Check **Skip Unattended Installation** (recommended so you can configure network manually).
2. **Hardware Configuration:**
   - **Processors:** Minimum **2 CPUs** (Allocating 2–4 vCPUs satisfies slide 11 of course specs).
   - **Base Memory:** Minimum **2048 MB (2 GB)** (3072 MB or 4096 MB recommended).
   - **Hard Disk:** Minimum **30 GB** (VDI Dynamically Allocated).

---

### Step 3.2: Dual Network Adapter Setup

Go to VM **Settings** $\rightarrow$ **Network**:

#### Adapter 1 (Bridged to Physical LAN):
- **Enable Network Adapter:** Checked ($\checkmark$)
- **Attached to:** **Bridged Adapter**
- **Name:** Select your macOS USB-C/Ethernet adapter connected to the TP-Link router (e.g., `USB 10/100/1000 LAN` or `AX88179A...`).
- Click **Advanced**:
  - **Promiscuous Mode:** **Allow All** (Critical: allows Flannel VXLAN overlay packets to flow between nodes).
  - **Cable Connected:** Checked ($\checkmark$).

#### Adapter 2 (NAT for Internet Access):
- Click **Adapter 2** tab.
- **Enable Network Adapter:** Checked ($\checkmark$)
- **Attached to:** **NAT**
- Click **Advanced**:
  - **Cable Connected:** Checked ($\checkmark$).

Click **OK** to save settings.

---

## 4. Ubuntu Server Installation & Configuration

1. Start the VM and follow the Ubuntu Server installer:
   - Select your language and keyboard.
   - For network setup during install, you may proceed with defaults or configure static IP right away.
   - In **Profile Setup**, enter:
     - Your name: `Chanatda`
     - Server name: `master-node`
     - Username: `sds` (or preferred)
     - Password: Choose a strong password.
   - In **SSH Setup**, check **Install OpenSSH server** ($\checkmark$).
   - Finish installation and reboot the VM.

---

## 5. Static IP & Dual-NIC Netplan Configuration

Log in to the Ubuntu VM. Run `ip link` to identify your network interface names:
```bash
ip -br link
```
Typically:
- `enp0s3` (or `eth0`) corresponds to **Adapter 1** (Bridged, connected to TP-Link router).
- `enp0s8` (or `eth1`) corresponds to **Adapter 2** (NAT, connected to internet via Mac Wi-Fi).

### Configure `/etc/netplan/01-netcfg.yaml`
```bash
sudo nano /etc/netplan/01-netcfg.yaml
```

Paste the following configuration (replace `enp0s3` and `enp0s8` with your actual interface names if different):

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    # Adapter 1: Bridged Adapter (Static IP for K8s Master on TP-Link LAN)
    enp0s3:
      dhcp4: no
      addresses:
        - 192.168.1.100/24
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]

    # Adapter 2: NAT Adapter (DHCP for Outbound Internet Access via Mac)
    enp0s8:
      dhcp4: yes
      dhcp4-overrides:
        route-metric: 100 # Prioritize internet default route through NAT
```

Apply and test:
```bash
sudo netplan apply
ip addr show enp0s3
```

Verify connectivity:
```bash
# 1. Ping the TP-Link router on the physical LAN
ping -c 3 192.168.1.1

# 2. Ping external internet (via NAT adapter)
ping -c 3 google.com
```

---

## 6. Host Prerequisites for K3s

Execute the following commands inside the VM:

```bash
# 1. Disable swap (Required for Kubernetes stability)
sudo swapoff -a
sudo sed -i '/swap/s/^/#/' /etc/fstab

# 2. Enable kernel modules for Flannel VXLAN overlay
sudo modprobe br_netfilter
sudo modprobe overlay

cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sudo sysctl --system

# 3. Create persistent storage directory for Redis state store
sudo mkdir -p /var/lib/werewolf-redis
sudo chmod 777 /var/lib/werewolf-redis
```

---

## 7. Turnkey K3s Master Installation

Clone the project repository inside your Ubuntu VM:
```bash
git clone https://github.com/<your-team>/sw-defined-werewolf.git
cd sw-defined-werewolf
```

Run the automated master installation script:
```bash
./scripts/install-master.sh
```

The script will:
1. Install K3s server with `--disable servicelb --flannel-backend=vxlan --node-ip=192.168.1.100`.
2. Configure `~/.kube/config` permissions.
3. Label the node as `node-role=control-plane`.
4. Output the cluster join token and exact join command for the 5 Raspberry Pis.

---

## 8. Verification & Next Steps

Verify the master node status:
```bash
kubectl get nodes -o wide
```
Output should display `master-node` in `Ready` status with internal IP `192.168.1.100`.

Now proceed to join the Raspberry Pi workers:
```bash
./scripts/join-workers.sh
```
