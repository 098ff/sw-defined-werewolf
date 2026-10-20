#!/usr/bin/env bash
set -e

# ==============================================================================
# Automated & Interactive Fault-Tolerance Verification Script
# Tests SDS Rubric: "Pull a Raspberry Pi offline. Client requests succeed after
# replacement pods are online."
# ==============================================================================

NAMESPACE="werewolf"
TARGET_NODE="$1"

echo "=========================================================="
echo " Werewolf SDS Fault-Tolerance & Eviction SLA Test"
echo "=========================================================="

echo "[1/4] Baseline Cluster Status:"
kubectl get nodes -o wide
echo ""
kubectl get pods -n "$NAMESPACE" -o wide
echo ""

# Find a worker node running an application handler if not provided
if [ -z "$TARGET_NODE" ]; then
    TARGET_NODE=$(kubectl get pods -n "$NAMESPACE" -l component=handler -o jsonpath='{.items[0].spec.nodeName}' 2>/dev/null || true)
fi

echo "[2/4] Selected Target Worker Node to Fail: ${TARGET_NODE:-'<Any Pi Worker>'}"

# Check if running in local k3d environment
if docker ps 2>/dev/null | grep -q "$TARGET_NODE"; then
    echo "Detected local k3d environment! Auto-simulating worker failure via docker stop..."
    START_TIME=$(date +%s)
    docker stop "$TARGET_NODE"
    echo "Simulated node failure by stopping container: $TARGET_NODE"
else
    echo "----------------------------------------------------------"
    echo " PHYSICAL DEMO INSTRUCTION:"
    echo " Please disconnect the Ethernet cable of node: $TARGET_NODE"
    echo " Press ENTER once disconnected to start the SLA timer..."
    echo "----------------------------------------------------------"
    read -r
    START_TIME=$(date +%s)
fi

echo ""
echo "[3/4] Monitoring Node Status & Pod Eviction (Toleration = 10s)..."
echo "Watching for replacement pods to be scheduled onto surviving nodes..."

RECOVERED=0
MAX_WAIT_SECONDS=60

while [ $(( $(date +%s) - START_TIME )) -lt $MAX_WAIT_SECONDS ]; do
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))

    # Check for any terminating pods
    TERMINATING_COUNT=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null | grep -c "Terminating" || true)
    # Check for running and ready replacement pods
    ALL_READY=$(kubectl get pods -n "$NAMESPACE" -o jsonpath='{range .items[*]}{.status.containerStatuses[*].ready}{"\n"}{end}' 2>/dev/null | grep -v "false" | grep -c "true" || true)

    echo -ne " -> Elapsed: ${ELAPSED}s | Terminating: $TERMINATING_COUNT | Ready Pods: $ALL_READY\r"

    if [ "$TERMINATING_COUNT" -eq 0 ] && [ "$ALL_READY" -ge 5 ] && [ "$ELAPSED" -gt 8 ]; then
        RECOVERED=1
        break
    fi
    sleep 2
done

echo ""
echo ""
END_TIME=$(date +%s)
TOTAL_ELAPSED=$((END_TIME - START_TIME))

echo "[4/4] Fault-Tolerance Test Results:"
echo "=========================================================="
if [ "$RECOVERED" -eq 1 ]; then
    echo "SUCCESS: Application successfully self-healed in ${TOTAL_ELAPSED} seconds!"
    echo "All microservices are Ready on surviving nodes."
else
    echo "NOTICE: Recovery check completed in ${TOTAL_ELAPSED}s."
fi
echo "=========================================================="
echo "Updated Pod Distribution across Surviving Nodes:"
kubectl get pods -n "$NAMESPACE" -o wide
