#!/usr/bin/env bash
set -e

# ==============================================================================
# Build Multi-Arch (linux/arm64) Container Images for Raspberry Pi Cluster
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."
SERVICES_DIR="$ROOT_DIR/services"
TAG="${1:-v1.0}"
REGISTRY="${2:-werewolf}"

echo "Building multi-arch images with tag: $TAG and registry: $REGISTRY"

SERVICES=("gateway" "frontend" "lobby" "gamemaster" "chat")

for SVC in "${SERVICES[@]}"; do
    echo "----------------------------------------------------------"
    echo " Building $SVC ($REGISTRY/$SVC:$TAG) for linux/arm64..."
    echo "----------------------------------------------------------"
    docker buildx build \
        --platform linux/arm64 \
        -t "$REGISTRY/$SVC:$TAG" \
        -f "$SERVICES_DIR/$SVC/Dockerfile" \
        "$ROOT_DIR" \
        --load
done

echo ""
echo "All 5 microservices built successfully for linux/arm64!"
