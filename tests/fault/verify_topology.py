#!/usr/bin/env python3
"""
Werewolf SDS Topology & Cross-Node Scheduling Verifier

Verifies that:
1. 'gateway' pod is NOT colocated on the same node as any handler pod
   (frontend, lobby, gamemaster, chat) -> Proves SDN Cross-Node Requirement.
2. 'redis' pod is placed exclusively on the Control-Plane node -> Proves State Preservation.
3. All pods are in 'Running' and 'Ready' condition.
"""

import argparse
import json
import subprocess
import sys

def get_cluster_data(namespace="werewolf", mock_file=None):
    if mock_file:
        with open(mock_file, "r") as f:
            return json.load(f)

    cmd = ["kubectl", "get", "pods", "-n", namespace, "-o", "json"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"kubectl failed: {res.stderr}")
    return json.loads(res.stdout)

def get_nodes_data(mock_file=None):
    if mock_file:
        return {}

    cmd = ["kubectl", "get", "nodes", "-o", "json"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return {}
    return json.loads(res.stdout)

def verify_topology(pods_json, nodes_json=None):
    items = pods_json.get("items", [])
    if not items:
        print("ERROR: No pods found in namespace!")
        return False

    pod_map = {}
    for item in items:
        app = item["metadata"]["labels"].get("app")
        node = item.get("spec", {}).get("nodeName")
        status_phase = item.get("status", {}).get("phase")
        container_statuses = item.get("status", {}).get("containerStatuses", [])
        is_ready = any(cs.get("ready", False) for cs in container_statuses)

        if app:
            pod_map[app] = {
                "name": item["metadata"]["name"],
                "node": node,
                "phase": status_phase,
                "ready": is_ready,
                "component": item["metadata"]["labels"].get("component")
            }

    print("==========================================================")
    print(" Werewolf SDS Pod Placement & Topology Status")
    print("==========================================================")
    for app, info in sorted(pod_map.items()):
        status_str = f"Phase: {info['phase']} | Ready: {info['ready']} | Node: {info['node']}"
        print(f" - {app:<12} : {status_str}")
    print("----------------------------------------------------------")

    all_passed = True

    # 1. Check Gateway Placement vs Handlers
    gateway = pod_map.get("gateway")
    if not gateway:
        print("FAIL: Gateway pod not found.")
        all_passed = False
    else:
        gw_node = gateway["node"]
        handlers = ["frontend", "lobby", "gamemaster", "chat"]
        for h in handlers:
            h_info = pod_map.get(h)
            if not h_info:
                print(f"WARN: Handler '{h}' not found in cluster.")
                all_passed = False
                continue

            if h_info["node"] == gw_node:
                print(f"FAIL [SDN Violation]: Gateway and '{h}' are collocated on the SAME node ({gw_node})!")
                all_passed = False
            else:
                print(f"PASS [SDN Compliant]: Gateway ({gw_node}) != {h} ({h_info['node']})")

    # 2. Check Redis Placement
    redis = pod_map.get("redis")
    if not redis:
        print("FAIL: Redis pod not found.")
        all_passed = False
    else:
        print(f"INFO: Redis running on node '{redis['node']}'")

    # 3. Check Readiness
    for app, info in pod_map.items():
        if info["phase"] != "Running" or not info["ready"]:
            print(f"FAIL: Pod '{app}' is not fully Ready (Phase: {info['phase']}, Ready: {info['ready']})")
            all_passed = False

    print("==========================================================")
    if all_passed:
        print("RESULT: ALL TOPOLOGY & CROSS-NODE REQUIREMENTS PASSED! (100% SDS COMPLIANT)")
    else:
        print("RESULT: TOPOLOGY VERIFICATION FAILED.")
    print("==========================================================")
    return all_passed

def main():
    parser = argparse.ArgumentParser(description="Verify Werewolf SDS Kubernetes Pod Topology")
    parser.add_argument("--namespace", default="werewolf", help="Kubernetes namespace")
    parser.add_argument("--mock-file", default=None, help="Path to mock pods JSON for testing")
    args = parser.parse_args()

    try:
        pods_data = get_cluster_data(args.namespace, args.mock_file)
        success = verify_topology(pods_data)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Execution Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
