#!/usr/bin/env python3
"""
Kubernetes Manifest Compliance Test Suite (Pure Python / Zero External Dependencies)

Validates that all Kubernetes manifests in k8s/ strictly comply with
course rubric requirements, architectural invariants, and memory ceilings.
"""

import os
import re
import unittest
from pathlib import Path

K8S_DIR = Path(__file__).resolve().parent.parent.parent / "k8s"

def read_manifest(filename: str) -> str:
    path = K8S_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    return path.read_text(encoding="utf-8")

class TestManifestCompliance(unittest.TestCase):

    def test_all_expected_manifests_exist(self):
        expected_files = [
            "namespace.yaml",
            "redis.yaml",
            "gateway.yaml",
            "frontend.yaml",
            "lobby.yaml",
            "gamemaster.yaml",
            "chat.yaml",
            "services.yaml",
            "metallb-config.yaml",
        ]
        for fname in expected_files:
            path = K8S_DIR / fname
            self.assertTrue(path.exists(), f"Missing manifest: {fname}")

    def test_gateway_anti_affinity_and_fallback(self):
        content = read_manifest("gateway.yaml")
        # Hard Pod Anti-Affinity
        self.assertIn("podAntiAffinity", content)
        self.assertIn("requiredDuringSchedulingIgnoredDuringExecution", content)
        self.assertIn("key: component", content)
        self.assertIn('values: ["handler"]', content)
        self.assertIn('topologyKey: "kubernetes.io/hostname"', content)

        # Tolerations for fast eviction (10s)
        self.assertIn('key: "node.kubernetes.io/unreachable"', content)
        self.assertIn('key: "node.kubernetes.io/not-ready"', content)
        self.assertIn("tolerationSeconds: 10", content)

        # Fallback tolerations for master/control-plane taints
        self.assertIn('key: "node-role.kubernetes.io/control-plane"', content)
        self.assertIn('key: "node-role.kubernetes.io/master"', content)

    def test_handler_components_and_labels(self):
        handler_files = ["frontend.yaml", "lobby.yaml", "gamemaster.yaml", "chat.yaml"]
        for fname in handler_files:
            content = read_manifest(fname)
            self.assertIn("component: handler", content, f"{fname} missing 'component: handler' label")
            self.assertIn("node-role: pi", content, f"{fname} missing 'node-role: pi' nodeSelector")

    def test_downward_api_trace_injection(self):
        # Backend microservices must receive POD_NAME and NODE_NAME via Downward API
        trace_files = ["gateway.yaml", "lobby.yaml", "gamemaster.yaml", "chat.yaml"]
        for fname in trace_files:
            content = read_manifest(fname)
            self.assertIn("name: POD_NAME", content, f"{fname} missing POD_NAME env var")
            self.assertIn("fieldPath: metadata.name", content, f"{fname} missing metadata.name fieldRef")
            self.assertIn("name: NODE_NAME", content, f"{fname} missing NODE_NAME env var")
            self.assertIn("fieldPath: spec.nodeName", content, f"{fname} missing spec.nodeName fieldRef")

    def test_resource_limits_ceilings(self):
        # Ceilings: memory <= 160Mi (64Mi for frontend, 512Mi for redis)
        backend_files = ["gateway.yaml", "lobby.yaml", "gamemaster.yaml", "chat.yaml"]
        for fname in backend_files:
            content = read_manifest(fname)
            mem_limit_match = re.search(r'memory:\s*["\']?(\d+)Mi["\']?', content)
            self.assertIsNotNone(mem_limit_match, f"Could not find memory spec in {fname}")
            # Ensure limit is <= 160Mi
            limits = re.findall(r'limits:.*?memory:\s*["\']?(\d+)Mi["\']?', content, re.DOTALL)
            for lim in limits:
                self.assertLessEqual(int(lim), 160, f"{fname} exceeds 160Mi memory limit: {lim}Mi")

        # Frontend limit <= 64Mi
        frontend_content = read_manifest("frontend.yaml")
        frontend_limits = re.findall(r'limits:.*?memory:\s*["\']?(\d+)Mi["\']?', frontend_content, re.DOTALL)
        for lim in frontend_limits:
            self.assertLessEqual(int(lim), 64, f"frontend.yaml exceeds 64Mi limit: {lim}Mi")

        # Redis limit <= 512Mi
        redis_content = read_manifest("redis.yaml")
        redis_limits = re.findall(r'limits:.*?memory:\s*["\']?(\d+)Mi["\']?', redis_content, re.DOTALL)
        for lim in redis_limits:
            self.assertLessEqual(int(lim), 512, f"redis.yaml exceeds 512Mi limit: {lim}Mi")

    def test_probes_configured_on_all_deployments(self):
        http_services = ["gateway.yaml", "frontend.yaml", "lobby.yaml", "gamemaster.yaml", "chat.yaml"]
        for fname in http_services:
            content = read_manifest(fname)
            self.assertIn("readinessProbe:", content, f"{fname} missing readinessProbe")
            self.assertIn("livenessProbe:", content, f"{fname} missing livenessProbe")
            self.assertIn("path: /health/ready", content, f"{fname} missing /health/ready path")
            self.assertIn("path: /health/live", content, f"{fname} missing /health/live path")

        # Redis has exec ping probe
        redis_content = read_manifest("redis.yaml")
        self.assertIn("readinessProbe:", redis_content, "redis.yaml missing readinessProbe")
        self.assertIn("livenessProbe:", redis_content, "redis.yaml missing livenessProbe")
        self.assertIn('command: ["redis-cli", "ping"]', redis_content, "redis.yaml missing redis-cli ping")

    def test_redis_pinned_to_control_plane(self):
        content = read_manifest("redis.yaml")
        self.assertIn("node-role: control-plane", content)
        self.assertIn("/var/lib/werewolf-redis", content)
        self.assertIn("hostPath:", content)

    def test_metallb_config_ip_range(self):
        content = read_manifest("metallb-config.yaml")
        self.assertIn("192.168.1.240-192.168.1.250", content)
        self.assertIn("IPAddressPool", content)
        self.assertIn("L2Advertisement", content)

    def test_gamemaster_demo_mode_configured(self):
        # Closes Issue #8: ensure DEMO_MODE and DEMO_SECRET are passed to gamemaster
        content = read_manifest("gamemaster.yaml")
        self.assertIn("name: DEMO_MODE", content)
        self.assertIn('value: "true"', content)
        self.assertIn("name: DEMO_SECRET", content)
        self.assertIn('value: "sds-werewolf-demo-secret"', content)

if __name__ == "__main__":
    unittest.main()
