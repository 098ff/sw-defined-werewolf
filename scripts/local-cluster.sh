#!/usr/bin/env bash
set -e

# ==============================================================================
# Local Multi-Node K8s Cluster Helper (using k3d)
# Simulates 1 Master + 5 Worker nodes topology locally on notebook
# ==============================================================================

CLUSTER_NAME="werewolf-local"
SERVERS=1
AGENTS=5
PORT="8080:80@loadbalancer"

CMD="${1:-up}"

check_k3d() {
    if ! command -v k3d &> /dev/null; then
        echo "Error: k3d is not installed on your system."
        echo "Install k3d via Homebrew on macOS:"
        echo "  brew install k3d"
        echo "Or via official install script:"
        echo "  curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash"
        exit 1
    fi
}

case "$CMD" in
    up)
        check_k3d
        echo "=========================================================="
        echo " Creating local simulated multi-node cluster: $CLUSTER_NAME"
        echo " Servers: $SERVERS (Master VM) | Agents: $AGENTS (Pi Workers)"
        echo " Exposed Port: $PORT"
        echo "=========================================================="

        if k3d cluster list | grep -q "$CLUSTER_NAME"; then
            echo "Cluster '$CLUSTER_NAME' already exists. Restarting nodes..."
            k3d cluster start "$CLUSTER_NAME"
        else
            k3d cluster create "$CLUSTER_NAME" \
                --servers "$SERVERS" \
                --agents "$AGENTS" \
                --port "$PORT"
        fi

        echo ""
        echo "Waiting for all cluster nodes to reach Ready state..."
        kubectl wait --for=condition=Ready nodes --all --timeout=60s

        echo "Applying production-matching node labels..."
        # Label master
        kubectl label node "k3d-$CLUSTER_NAME-server-0" node-role=control-plane --overwrite || true

        # Label workers
        for i in $(seq 0 $((AGENTS - 1))); do
            kubectl label node "k3d-$CLUSTER_NAME-agent-$i" node-role=pi --overwrite || true
        done

        echo ""
        echo "=========================================================="
        echo " Local Multi-Node Cluster is Ready!"
        echo "=========================================================="
        kubectl get nodes -o wide --show-labels
        echo ""
        echo "Next step: Deploy the Werewolf stack using:"
        echo "  ./scripts/build-images.sh --local"
        echo "  ./scripts/deploy.sh"
        ;;

    down)
        check_k3d
        echo "Deleting local cluster '$CLUSTER_NAME'..."
        k3d cluster delete "$CLUSTER_NAME"
        echo "Local cluster deleted."
        ;;

    status)
        check_k3d
        kubectl get nodes -o wide --show-labels
        echo ""
        kubectl get pods -n werewolf -o wide 2>/dev/null || true
        ;;

    *)
        echo "Usage: $0 {up|down|status}"
        exit 1
        ;;
esac
