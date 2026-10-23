#!/usr/bin/env bash
set -e

# ==============================================================================
# Join 5x Raspberry Pi 3 B+ Workers to K3s Master Cluster
# Can be run from Master Node (via SSH) or prints instructions for manual run
# ==============================================================================

MASTER_IP="${2:-192.168.1.100}"
PI_USER="${PI_USER:-pi}"
K3S_VERSION="${K3S_VERSION:-v1.28.8+k3s1}"
WORKER_IPS=("192.168.1.101" "192.168.1.102" "192.168.1.103" "192.168.1.104" "192.168.1.105")

# 1. Resolve Token
if [ -n "$1" ]; then
    NODE_TOKEN="$1"
elif [ -f "/var/lib/rancher/k3s/server/node-token" ]; then
    NODE_TOKEN=$(sudo cat /var/lib/rancher/k3s/server/node-token)
else
    echo "Error: K3s node token not found."
    echo "Usage: $0 <NODE_TOKEN> [MASTER_IP]"
    exit 1
fi

echo "=========================================================="
echo " Joining 5x Raspberry Pi Workers to Master ($MASTER_IP)"
echo "=========================================================="

JOIN_CMD="curl -sfL https://get.k3s.io | sudo INSTALL_K3S_VERSION=\"$K3S_VERSION\" K3S_URL=https://$MASTER_IP:6443 K3S_TOKEN=\"$NODE_TOKEN\" sh -"

# 2. Iterate through worker IPs and attempt SSH installation
for IP in "${WORKER_IPS[@]}"; do
    echo "----------------------------------------------------------"
    echo " Connecting to Worker Node: $IP ..."
    echo "----------------------------------------------------------"
    if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$PI_USER@$IP" "$JOIN_CMD" 2>/dev/null; then
        echo "Successfully triggered K3s agent join on $IP"
    else
        echo "Notice: SSH to $PI_USER@$IP failed or timed out."
        echo "You can manually run this command on $IP:"
        echo "  $JOIN_CMD"
    fi
done

echo ""
echo "Waiting 15 seconds for nodes to register with the master..."
sleep 15

# 3. Label Pi Worker Nodes (select nodes that are not control-plane)
echo "Applying 'node-role=pi' labels to worker nodes..."
PI_NODES=$(kubectl get nodes -l '!node-role.kubernetes.io/control-plane,!node-role.kubernetes.io/master,!node-role=control-plane' -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)

for NODE in $PI_NODES; do
    kubectl label node "$NODE" node-role=pi --overwrite || true
    echo "Labeled node: $NODE -> node-role=pi"
done

echo ""
echo "=========================================================="
echo " Current Cluster Node Status:"
echo "=========================================================="
kubectl get nodes -o wide
