#!/usr/bin/env bash
set -e

# ==============================================================================
# Pre-pull Container Images across all 5 Raspberry Pi Workers
# ==============================================================================

WORKER_IPS=("192.168.1.101" "192.168.1.102" "192.168.1.103" "192.168.1.104" "192.168.1.105")
PI_USER="${PI_USER:-pi}"
TAG="${1:-v1.0}"
REGISTRY="${2:-werewolf}"
SERVICES=("gateway" "frontend" "lobby" "gamemaster" "chat")

echo "Pre-pulling images to all 5 Raspberry Pi workers..."

for IP in "${WORKER_IPS[@]}"; do
    echo "=========================================================="
    echo " Connecting to Pi Worker: $IP ..."
    echo "=========================================================="
    for SVC in "${SERVICES[@]}"; do
        IMAGE="$REGISTRY/$SVC:$TAG"
        echo " -> Pulling $IMAGE on $IP..."
        ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$PI_USER@$IP" \
            "sudo k3s ctr images pull docker.io/$IMAGE || sudo docker pull $IMAGE || true" || {
                echo "Warning: Could not connect to $IP or pull $IMAGE. Skipping..."
            }
    done
done

echo ""
echo "Pre-pull sequence completed across available workers."
