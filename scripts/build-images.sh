#!/usr/bin/env bash
set -e

# ==============================================================================
# Build Container Images for Werewolf SDS Microservices
# Supports:
#   1. ARM64 (for physical Raspberry Pi cluster): ./scripts/build-images.sh
#   2. Local Arch (for local k3d / docker-compose testing): ./scripts/build-images.sh --local
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."
SERVICES_DIR="$ROOT_DIR/services"

BUILD_PLATFORM="linux/arm64"
TAG="v1.0"
REGISTRY="werewolf"

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --local)
            BUILD_PLATFORM=""
            shift
            ;;
        --platform)
            BUILD_PLATFORM="$2"
            shift 2
            ;;
        --tag)
            TAG="$2"
            shift 2
            ;;
        --registry)
            REGISTRY="$2"
            shift 2
            ;;
        *)
            if [ -z "$TAG_SET" ]; then
                TAG="$1"
                TAG_SET=1
            elif [ -z "$REG_SET" ]; then
                REGISTRY="$1"
                REG_SET=1
            fi
            shift
            ;;
    esac
done

echo "=========================================================="
echo " Building Werewolf SDS Microservices"
echo " Registry : $REGISTRY"
echo " Tag      : $TAG"
if [ -n "$BUILD_PLATFORM" ]; then
    echo " Platform : $BUILD_PLATFORM (Physical Pi Production)"
else
    echo " Platform : Host Native (Local Dev / k3d Testing)"
fi
echo "=========================================================="

SERVICES=("gateway" "frontend" "lobby" "gamemaster" "chat")

for SVC in "${SERVICES[@]}"; do
    echo "----------------------------------------------------------"
    echo " Building $SVC ($REGISTRY/$SVC:$TAG) ..."
    echo "----------------------------------------------------------"

    if [ -n "$BUILD_PLATFORM" ]; then
        docker buildx build \
            --platform "$BUILD_PLATFORM" \
            -t "$REGISTRY/$SVC:$TAG" \
            -f "$SERVICES_DIR/$SVC/Dockerfile" \
            "$ROOT_DIR" \
            --load
    else
        docker build \
            -t "$REGISTRY/$SVC:$TAG" \
            -f "$SERVICES_DIR/$SVC/Dockerfile" \
            "$ROOT_DIR"
    fi
done

echo ""
echo "All 5 microservices built successfully!"
