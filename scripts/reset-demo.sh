#!/usr/bin/env bash
set -e

# ==============================================================================
# Reset Werewolf Demo Environment & State
# ==============================================================================

echo "=========================================================="
echo " Resetting Werewolf Demo Environment..."
echo "=========================================================="

# Flush Redis keys on the Master Node
echo "Flushing Redis State Store..."
REDIS_POD=$(kubectl get pod -n werewolf -l app=redis -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

if [ -n "$REDIS_POD" ]; then
    kubectl exec -n werewolf "$REDIS_POD" -- redis-cli FLUSHALL || echo "Notice: Redis flush skipped."
else
    echo "Notice: Redis pod not currently running."
fi

# Restart application deployments to restore baseline placement
echo "Restarting application microservices..."
kubectl rollout restart -n werewolf deployment/gateway || true
kubectl rollout restart -n werewolf deployment/frontend || true
kubectl rollout restart -n werewolf deployment/lobby || true
kubectl rollout restart -n werewolf deployment/gamemaster || true
kubectl rollout restart -n werewolf deployment/chat || true

echo "Waiting for pods to stabilize..."
kubectl rollout status -n werewolf deployment/gateway --timeout=60s || true

echo ""
echo "Demo environment reset complete. Current cluster status:"
kubectl get pods -n werewolf -o wide
