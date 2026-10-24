#!/usr/bin/env bash
set -e

# ==============================================================================
# K3s Control-Plane (Master Node) Automated Setup Script
# Run this script directly on the Ubuntu Master VM (VirtualBox / Physical)
# ==============================================================================

MASTER_IP="${1:-192.168.0.50}"
K3S_VERSION="${K3S_VERSION:-v1.28.8+k3s1}"
# Bridged LAN interface; without this flannel picks the NAT interface (default route) and cross-node pod traffic breaks
FLANNEL_IFACE="${FLANNEL_IFACE:-enp0s8}"
INSTALL_DIR="/var/lib/werewolf-redis"

echo "=========================================================="
echo " Starting K3s Control-Plane Master Node Setup"
echo " Target Master IP: $MASTER_IP"
echo "=========================================================="

# 1. Check Root / Sudo
if [ "$EUID" -ne 0 ]; then
    echo "This script must be run with sudo privileges. Re-running with sudo..."
    exec sudo "$0" "$@"
fi

# 2. Host Prerequisites: Disable Swap & Enable Overlay Modules
echo "[1/6] Configuring Host Kernel & Swap Settings..."
swapoff -a
sed -i '/swap/s/^/#/' /etc/fstab || true

modprobe br_netfilter || true
modprobe overlay || true

cat <<EOF > /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sysctl --system > /dev/null

# 3. Prepare Persistent Storage for Redis
echo "[2/6] Preparing Persistent Storage Directory at $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
chmod 777 "$INSTALL_DIR"

# 4. Install K3s Control-Plane
echo "[3/6] Installing K3s Server version $K3S_VERSION (Flannel VXLAN, ServiceLB + Traefik Disabled)..."
# Traefik is disabled so it does not grab the first MetalLB VIP (192.168.0.240) meant for gateway-service
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="$K3S_VERSION" INSTALL_K3S_EXEC="--disable servicelb --disable traefik --flannel-backend=vxlan --flannel-iface=$FLANNEL_IFACE --node-ip=$MASTER_IP --advertise-address=$MASTER_IP --write-kubeconfig-mode=0644" sh -

# 5. Set up Kubeconfig Permissions for Normal User
echo "[4/6] Setting up Kubeconfig Permissions..."
CURRENT_USER="${SUDO_USER:-$USER}"
USER_HOME=$(eval echo "~$CURRENT_USER")

mkdir -p "$USER_HOME/.kube"
cp /etc/rancher/k3s/k3s.yaml "$USER_HOME/.kube/config"
chown -R "$CURRENT_USER:$CURRENT_USER" "$USER_HOME/.kube"
chmod 600 "$USER_HOME/.kube/config"
chmod 644 /etc/rancher/k3s/k3s.yaml

# 6. Wait for Node to be Ready and Label Master
echo "[5/6] Waiting for Master Node to reach Ready state..."
kubectl wait --for=condition=Ready node --all --timeout=60s 2>/dev/null || sleep 5
MASTER_NODE_NAME=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
if [ -n "$MASTER_NODE_NAME" ]; then
    kubectl label node "$MASTER_NODE_NAME" node-role=control-plane --overwrite
    echo "Labeled master node: $MASTER_NODE_NAME -> node-role=control-plane"
fi

# 7. Retrieve Cluster Join Token
NODE_TOKEN=$(cat /var/lib/rancher/k3s/server/node-token)

echo ""
echo "=========================================================="
echo " K3s Master Installation Complete!"
echo "=========================================================="
echo "Master Node Name : $MASTER_NODE_NAME"
echo "Master Node IP   : $MASTER_IP"
echo "Cluster Token    : $NODE_TOKEN"
echo ""
echo "To join Raspberry Pi workers to this master, run on each Pi:"
echo "----------------------------------------------------------"
echo "curl -sfL https://get.k3s.io | K3S_URL=https://$MASTER_IP:6443 K3S_TOKEN=\"$NODE_TOKEN\" sh -"
echo "----------------------------------------------------------"
echo "Or run the automated helper: ./scripts/join-workers.sh $NODE_TOKEN $MASTER_IP"
echo "=========================================================="
