#!/usr/bin/env bash
set -e

# ==============================================================================
# Fault Tolerance Live Monitor for Demo
# ==============================================================================

echo "=========================================================="
echo " Starting Fault Tolerance Live Monitor..."
echo " Disconnect a Raspberry Pi now to demonstrate recovery."
echo " Press Ctrl+C to stop watching."
echo "=========================================================="

echo "Initial Node & Pod Placement:"
kubectl get nodes -o wide
echo ""
kubectl get pods -n werewolf -o wide
echo ""
echo "Streaming Pod Events (Watching for Evictions & Replacements)..."
kubectl get pods -n werewolf -o wide -w
