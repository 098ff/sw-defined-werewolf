#!/usr/bin/env bash
set -e

# ==============================================================================
# Pre-pull or Import Container Images across all 5 Raspberry Pi Workers
# Supports:
#   1. Remote pull: ./scripts/pre-pull.sh [TAG] [REGISTRY]
#   2. Offline tar import: ./scripts/pre-pull.sh --import-tar [ARCHIVE_PATH]
# ==============================================================================

WORKER_IPS=("192.168.0.101" "192.168.0.102" "192.168.0.103" "192.168.0.104" "192.168.0.105")
PI_USER="${PI_USER:-pi}"

if [ "$1" == "--import-tar" ]; then
    ARCHIVE_PATH="${2:-werewolf-images.tar.gz}"
    if [ ! -f "$ARCHIVE_PATH" ]; then
        echo "Error: Archive file not found at '$ARCHIVE_PATH'"
        exit 1
    fi

    echo "=========================================================="
    echo " Distributing & Importing Offline Image Archive ($ARCHIVE_PATH)"
    echo "=========================================================="

    for IP in "${WORKER_IPS[@]}"; do
        echo "----------------------------------------------------------"
        echo " Transferring archive to $IP ..."
        echo "----------------------------------------------------------"
        scp -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$ARCHIVE_PATH" "$PI_USER@$IP:/tmp/werewolf-images.tar.gz" || {
            echo "Warning: Could not scp to $IP. Skipping..."
            continue
        }

        echo " Importing archive into k3s containerd on $IP ..."
        ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$PI_USER@$IP" \
            "sudo k3s ctr images import /tmp/werewolf-images.tar.gz && rm -f /tmp/werewolf-images.tar.gz" || {
            echo "Warning: Import failed on $IP."
        }
    done

    echo ""
    echo "Offline image distribution complete!"
    exit 0
fi

TAG="${1:-v1.0}"
REGISTRY="${2:-werewolf}"
SERVICES=("gateway" "frontend" "lobby" "gamemaster" "chat")

echo "=========================================================="
echo " Pre-pulling images to all 5 Raspberry Pi workers..."
echo " Tag: $TAG | Registry: $REGISTRY"
echo "=========================================================="

for IP in "${WORKER_IPS[@]}"; do
    echo "----------------------------------------------------------"
    echo " Connecting to Pi Worker: $IP ..."
    echo "----------------------------------------------------------"
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
