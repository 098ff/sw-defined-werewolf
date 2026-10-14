import os
from typing import Dict

def get_service_trace(service_name: str) -> Dict[str, str]:
    """
    Retrieves execution trace identity from Kubernetes Downward API environment variables.
    Falls back to local default identifiers when running outside Kubernetes.
    """
    return {
        "service": service_name,
        "pod": os.getenv("POD_NAME", f"{service_name}-local"),
        "node": os.getenv("NODE_NAME", "node-local")
    }
