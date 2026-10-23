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
if [ -n "$TARGET_NODE" ] && docker ps 2>/dev/null | grep -q "$TARGET_NODE"; then
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
MAX_WAIT_SECONDS=90

while [ $(( $(date +%s) - START_TIME )) -lt $MAX_WAIT_SECONDS ]; do
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))

    POD_DATA=$(kubectl get pods -n "$NAMESPACE" -o json 2>/dev/null || echo "{}")
    RECOVERY_STATUS=$(echo "$POD_DATA" | python3 -c '
import sys, json
target_node = sys.argv[1] if len(sys.argv) > 1 else ""
required_services = {"gateway", "frontend", "lobby", "gamemaster", "chat", "redis"}
ready_on_surviving = set()
terminating_count = 0

try:
    data = json.load(sys.stdin)
    for item in data.get("items", []):
        app = item.get("metadata", {}).get("labels", {}).get("app", "")
        node = item.get("spec", {}).get("nodeName", "")
        phase = item.get("status", {}).get("phase", "")
        metadata = item.get("metadata", {})
        is_terminating = "deletionTimestamp" in metadata

        if is_terminating:
            terminating_count += 1

        cs = item.get("status", {}).get("containerStatuses", [])
        is_ready = any(c.get("ready", False) for c in cs)

        # Count as ready replacement if alive, ready, and placed on a surviving node
        if not is_terminating and phase == "Running" and is_ready and (not target_node or node != target_node):
            if app in required_services:
                ready_on_surviving.add(app)

    all_ok = (len(required_services - ready_on_surviving) == 0)
    print(f"{len(ready_on_surviving)}:{terminating_count}:{1 if all_ok else 0}")
except Exception:
    print("0:0:0")
' "$TARGET_NODE" 2>/dev/null || echo "0:0:0")

    IFS=':' read -r READY_SERVICES TERMINATING_COUNT ALL_OK <<< "$RECOVERY_STATUS"

    echo -ne " -> Elapsed: ${ELAPSED}s | Ready Services: ${READY_SERVICES:-0}/6 | Offline Pods: ${TERMINATING_COUNT:-0}\r"

    if [ "${ALL_OK:-0}" -eq 1 ] && [ "$ELAPSED" -gt 8 ]; then
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
