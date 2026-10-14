#!/usr/bin/env bash
set -e

# ==============================================================================
# Werewolf SDS Automated Kubernetes Deployment Script (Demo Single Command)
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$SCRIPT_DIR/../k8s"

echo "=========================================================="
echo " Starting Werewolf SDS Automated Deployment..."
echo "=========================================================="

# 1. Create / Apply Namespace
echo "[1/6] Applying Namespace..."
kubectl apply -f "$K8S_DIR/namespace.yaml"

# 2. Deploy Redis onto Master Node
echo "[2/6] Deploying Redis (Pinned to Control-Plane Master)..."
kubectl apply -f "$K8S_DIR/redis.yaml"

echo "Waiting for Redis to become Ready..."
kubectl rollout status -n werewolf deployment/redis --timeout=60s

# 3. Deploy Gateway (with Anti-Affinity constraints)
echo "[3/6] Deploying Gateway (Entrypoint Proxy)..."
kubectl apply -f "$K8S_DIR/gateway.yaml"

# 4. Deploy Handlers (Frontend, Lobby, GameMaster, Chat)
echo "[4/6] Deploying Handler Services across Pi Workers..."
kubectl apply -f "$K8S_DIR/frontend.yaml"
kubectl apply -f "$K8S_DIR/lobby.yaml"
kubectl apply -f "$K8S_DIR/gamemaster.yaml"
kubectl apply -f "$K8S_DIR/chat.yaml"
kubectl apply -f "$K8S_DIR/services.yaml"

# 5. Apply MetalLB LoadBalancer Config
echo "[5/6] Applying MetalLB Layer-2 Configuration..."
kubectl apply -f "$K8S_DIR/metallb-config.yaml"

# 6. Wait for all Deployments to Roll Out
echo "[6/6] Verifying Pod Readiness across all Nodes..."
kubectl rollout status -n werewolf deployment/gateway --timeout=90s
kubectl rollout status -n werewolf deployment/frontend --timeout=90s
kubectl rollout status -n werewolf deployment/lobby --timeout=90s
kubectl rollout status -n werewolf deployment/gamemaster --timeout=90s
kubectl rollout status -n werewolf deployment/chat --timeout=90s

echo ""
echo "=========================================================="
echo " Deployment Successfully Completed!"
echo "=========================================================="
kubectl get nodes -o wide
echo ""
kubectl get pods -n werewolf -o wide
echo ""
kubectl get svc -n werewolf -o wide
