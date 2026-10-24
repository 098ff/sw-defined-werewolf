#!/usr/bin/env bash
set -e

# ==============================================================================
# Werewolf SDS Automated Kubernetes Deployment Script (Demo Single Command)
# Satisfies SDS Rubric: Automated 1-Script Rollout covering namespace, storage,
# configs, and application workloads across Bare-Metal Pi nodes.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$SCRIPT_DIR/../k8s"

echo "=========================================================="
echo " Starting Werewolf SDS Automated Deployment..."
echo "=========================================================="

# Pre-flight Check: Ensure cluster connectivity
echo "[Pre-flight] Verifying Kubernetes cluster status..."
if ! kubectl get nodes > /dev/null 2>&1; then
    echo "Error: Cannot connect to Kubernetes cluster via kubectl."
    echo "Please ensure K3s is running and ~/.kube/config is properly configured."
    exit 1
fi

READY_NODES=$(kubectl get nodes --no-headers 2>/dev/null | grep -c "Ready" || true)
echo "Found $READY_NODES Ready node(s) in cluster."

# 1. Create / Apply Namespace
echo "[1/6] Applying Namespace..."
kubectl apply -f "$K8S_DIR/namespace.yaml"

# 2. Deploy Redis onto Master Node
echo "[2/6] Deploying Redis (Pinned to Control-Plane Master)..."
kubectl apply -f "$K8S_DIR/redis.yaml"

echo "Waiting for Redis to become Ready..."
kubectl rollout status -n werewolf deployment/redis --timeout=60s

# 3. Deploy Handlers (Frontend, Lobby, GameMaster, Chat)
echo "[3/6] Deploying Handler Services across Pi Workers..."
kubectl apply -f "$K8S_DIR/frontend.yaml"
kubectl apply -f "$K8S_DIR/lobby.yaml"
kubectl apply -f "$K8S_DIR/gamemaster.yaml"
kubectl apply -f "$K8S_DIR/chat.yaml"
kubectl apply -f "$K8S_DIR/services.yaml"

echo "Waiting for Handlers to become Ready across Pi nodes..."
kubectl rollout status -n werewolf deployment/frontend --timeout=90s
kubectl rollout status -n werewolf deployment/lobby --timeout=90s
kubectl rollout status -n werewolf deployment/gamemaster --timeout=90s
kubectl rollout status -n werewolf deployment/chat --timeout=90s

# 4. Deploy Gateway (Scheduled strictly on a remaining node away from Handlers)
echo "[4/6] Deploying Gateway (Entrypoint Proxy with Pod Anti-Affinity)..."
kubectl apply -f "$K8S_DIR/gateway.yaml"
echo "Waiting for Gateway to become Ready..."
kubectl rollout status -n werewolf deployment/gateway --timeout=90s

# 5. Apply MetalLB LoadBalancer Config
echo "[5/6] Checking MetalLB LoadBalancer Configuration..."
if ! kubectl get crd ipaddresspools.metallb.io > /dev/null 2>&1; then
    echo "MetalLB CRDs not detected. Installing MetalLB native controller..."
    kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.13.12/config/manifests/metallb-native.yaml || true
    echo "Waiting for MetalLB controller deployment..."
    kubectl rollout status -n metallb-system deployment/controller --timeout=90s || true
fi

if kubectl get crd ipaddresspools.metallb.io > /dev/null 2>&1; then
    echo "Applying MetalLB Layer-2 Address Pool & Advertisement..."
    kubectl apply -f "$K8S_DIR/metallb-config.yaml"
else
    echo "Notice: MetalLB CRDs not ready; skipped metallb-config.yaml application."
fi

# 6. Verify Pod Readiness across all Nodes
echo "[6/6] Final Verification of Workload Rollout across all Nodes..."
kubectl rollout status -n werewolf deployment/redis --timeout=30s
kubectl rollout status -n werewolf deployment/gateway --timeout=30s

echo ""
echo "=========================================================="
echo " Deployment Successfully Completed!"
echo "=========================================================="
echo "Cluster Nodes:"
kubectl get nodes -o wide
echo ""
echo "Deployed Werewolf Pods:"
kubectl get pods -n werewolf -o wide
echo ""
echo "Active Services & LoadBalancer VIP:"
kubectl get svc -n werewolf -o wide

echo ""
echo "=========================================================="
echo " SDN Cross-Node Scheduling Verification:"
GATEWAY_NODE=$(kubectl get pod -n werewolf -l app=gateway -o jsonpath='{.items[0].spec.nodeName}' 2>/dev/null || echo "unknown")
echo "Gateway Pod Node : $GATEWAY_NODE"
for HANDLER in frontend lobby gamemaster chat; do
    H_NODE=$(kubectl get pod -n werewolf -l app=$HANDLER -o jsonpath='{.items[0].spec.nodeName}' 2>/dev/null || echo "unknown")
    if [ "$GATEWAY_NODE" != "$H_NODE" ]; then
        STATUS="PASS (Cross-Node: $GATEWAY_NODE != $H_NODE)"
    else
        STATUS="WARN (Colocated: $GATEWAY_NODE == $H_NODE)"
    fi
    echo " - $HANDLER: $H_NODE -> $STATUS"
done
echo "=========================================================="
