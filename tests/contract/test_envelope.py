"""Contract tests: every gateway API response must match the standard envelope (contracts/api-contract.md §2)."""
import importlib.util
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from common.schemas import ApiResponse

# Load by path: every service ships an `app` package, so a plain import would collide.
_spec = importlib.util.spec_from_file_location(
    "gateway_main", Path(__file__).resolve().parents[2] / "services" / "gateway" / "app" / "main.py")
gateway = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gateway)

HANDLER_HOP = {"service": "gamemaster", "pod": "gm-1", "node": "pi-04"}

UPSTREAM_CASES = {
    "success": lambda req: httpx.Response(200, json={"ok": True, "data": {"phase": "DAY"}, "trace": [HANDLER_HOP]}),
    "envelope_error": lambda req: httpx.Response(409, json={"ok": False, "error": {"code": "PHASE_VERSION_CONFLICT", "message": "stale"}, "trace": [HANDLER_HOP]}),
    "fastapi_detail": lambda req: httpx.Response(422, json={"detail": [{"loc": ["body", "target_id"], "msg": "field required"}]}),
    "non_json": lambda req: httpx.Response(500, content=b"Internal Server Error"),
    "bare_json": lambda req: httpx.Response(200, json={"status": "UP"}),
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("POD_NAME", "gateway-1")
    monkeypatch.setenv("NODE_NAME", "pi-01")
    with TestClient(gateway.app) as tc:
        yield tc


@pytest.mark.parametrize("case", list(UPSTREAM_CASES))
def test_api_responses_match_envelope(client, case):
    gateway.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(UPSTREAM_CASES[case]))
    r = client.post("/api/game/rooms/WOLF/vote", json={"phase_version": 1, "target_id": "SKIP"})
    body = r.json()

    parsed = ApiResponse.model_validate(body)
    assert parsed.request_id.startswith("req-")
    assert parsed.trace[0].service == "gateway"
    if parsed.ok:
        assert "data" in body and "error" not in body
    else:
        assert parsed.error is not None and parsed.error.code and "data" not in body


def test_upstream_down_still_returns_envelope(client):
    def handler(req):
        raise httpx.ConnectError("refused", request=req)
    gateway.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = client.get("/api/lobby/rooms/WOLF")
    parsed = ApiResponse.model_validate(r.json())
    assert r.status_code == 503 and not parsed.ok and parsed.error.code == "SERVICE_UNAVAILABLE"


def test_cross_node_trace_shape(client):
    gateway.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(UPSTREAM_CASES["success"]))
    trace = client.get("/api/game/rooms/WOLF/state").json()["trace"]
    assert len(trace) >= 2
    assert trace[0]["node"] != trace[1]["node"], "SDN validation: gateway and handler must run on different nodes"
