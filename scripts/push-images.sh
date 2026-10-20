#!/usr/bin/env bash
set -e

# ==============================================================================
# Push or Export Container Images for Werewolf SDS Microservices
# Supports:
#   1. Registry push: ./scripts/push-images.sh [TAG] [REGISTRY]
#   2. Offline export: ./scripts/push-images.sh --save-tar [OUTPUT_FILE]
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAG="${1:-v1.0}"
REGISTRY="${2:-werewolf}"
SERVICES=("gateway" "frontend" "lobby" "gamemaster" "chat")

if [ "$1" == "--save-tar" ]; then
    OUTPUT_FILE="${2:-$SCRIPT_DIR/../werewolf-images.tar.gz}"
    echo "=========================================================="
    echo " Exporting all 5 microservice images to offline archive..."
    echo " Output Archive: $OUTPUT_FILE"
    echo "=========================================================="

    IMAGE_LIST=()
    for SVC in "${SERVICES[@]}"; do
        IMAGE_LIST+=("$REGISTRY/$SVC:$TAG")
    done

    echo "Packaging images: ${IMAGE_LIST[*]} ..."
    docker save "${IMAGE_LIST[@]}" | gzip > "$OUTPUT_FILE"

    echo ""
    echo "Successfully generated offline image archive: $OUTPUT_FILE"
    echo "Archive size: $(du -h "$OUTPUT_FILE" | cut -f1)"
    echo "You can transfer this file to Raspberry Pis and import via:"
    echo "  sudo k3s ctr images import $OUTPUT_FILE"
    exit 0
fi

echo "=========================================================="
echo " Pushing Container Images to Registry ($REGISTRY)"
echo " Tag: $TAG"
echo "=========================================================="

for SVC in "${SERVICES[@]}"; do
    IMAGE="$REGISTRY/$SVC:$TAG"
    echo "Pushing $IMAGE ..."
    docker push "$IMAGE"
done

echo ""
echo "All 5 microservice images pushed successfully!"
