"""Unit tests for the gateway reverse proxy (services/gateway)."""
import json
import importlib.util
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

# Load by path: every service ships an `app` package, so a plain import would collide.
_spec = importlib.util.spec_from_file_location(
    "gateway_main", Path(__file__).resolve().parents[2] / "services" / "gateway" / "app" / "main.py")
gateway = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gateway)

GM_HOP = {"service": "gamemaster", "pod": "gamemaster-abc", "node": "pi-04"}


@pytest.fixture
def make_client(monkeypatch):
    """Returns a factory: make_client(handler) -> TestClient whose upstream calls hit `handler`."""
    monkeypatch.setenv("POD_NAME", "gateway-xyz")
    monkeypatch.setenv("NODE_NAME", "pi-01")
    with TestClient(gateway.app) as tc:
        def factory(handler):
            gateway.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            return tc
        yield factory


def test_attaches_request_id_and_prepends_gateway_hop(make_client):
    seen = {}

    def handler(req: httpx.Request):
        seen["request_id"] = req.headers.get("X-Request-ID")
        seen["auth"] = req.headers.get("Authorization")
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"ok": True, "data": {"phase": "NIGHT"}, "request_id": "ignored", "trace": [GM_HOP]})

    client = make_client(handler)
    r = client.get("/api/game/rooms/WOLF/state", headers={"Authorization": "Bearer tok"})
    body = r.json()

    assert r.status_code == 200
    assert seen["request_id"].startswith("req-")
    assert seen["auth"] == "Bearer tok"
    assert seen["url"] == f"{gateway.GAMEMASTER_URL}/api/game/rooms/WOLF/state"
    assert body["request_id"] == seen["request_id"] == r.headers["X-Request-ID"]
    assert body["trace"] == [{"service": "gateway", "pod": "gateway-xyz", "node": "pi-01"}, GM_HOP]
    assert body["data"] == {"phase": "NIGHT"}


def test_inbound_request_id_is_not_trusted(make_client):
    seen = {}
    def handler(req):
        seen["rid"] = req.headers["X-Request-ID"]
        return httpx.Response(200, json={"ok": True, "data": {}, "trace": []})
    make_client(handler).get("/api/chat/rooms/WOLF/messages", headers={"X-Request-ID": "spoofed"})
    assert seen["rid"] != "spoofed"


def test_query_string_and_body_forwarded(make_client):
    seen = {}
    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content) if req.content else None
        return httpx.Response(200, json={"ok": True, "data": {"message_id": 3}, "trace": []})
    client = make_client(handler)
    client.get("/api/chat/rooms/WOLF/messages?after_id=7")
    assert seen["url"].endswith("/api/chat/rooms/WOLF/messages?after_id=7")
    client.post("/api/chat/rooms/WOLF/messages", json={"channel": "PUBLIC", "text": "hi"})
    assert seen["body"] == {"channel": "PUBLIC", "text": "hi"}


def test_routes_to_correct_backend(make_client):
    hits = []
    def handler(req):
        hits.append(f"{req.url.scheme}://{req.url.host}:{req.url.port}")
        return httpx.Response(200, json={"ok": True, "data": {}, "trace": []})
    client = make_client(handler)
    client.post("/api/lobby/rooms", json={"name": "Alice"})
    client.get("/api/game/rooms/WOLF/state")
    client.get("/api/chat/rooms/WOLF/messages")
    assert hits == [gateway.LOBBY_URL, gateway.GAMEMASTER_URL, gateway.CHAT_URL]


def test_trace_from_header_when_body_has_none(make_client):
    def handler(req):
        return httpx.Response(200, json={"ok": True, "data": {}}, headers={"X-Trace": json.dumps(GM_HOP)})
    body = make_client(handler).get("/api/game/rooms/WOLF/state").json()
    assert [h["service"] for h in body["trace"]] == ["gateway", "gamemaster"]


@pytest.mark.parametrize("status,code", [(400, "INVALID_REQUEST"), (401, "INVALID_TOKEN"), (403, "HOST_ONLY"),
                                         (404, "ROOM_NOT_FOUND"), (409, "ROOM_FULL")])
def test_forwards_backend_errors_without_swallowing(make_client, status, code):
    def handler(req):
        return httpx.Response(status, json={"ok": False, "error": {"code": code, "message": "details here"},
                                            "trace": [{"service": "lobby", "pod": "lobby-1", "node": "pi-02"}]})
    r = make_client(handler).post("/api/lobby/rooms/WOLF/join", json={"name": "Zed"})
    body = r.json()
    assert r.status_code == status
    assert body["ok"] is False
    assert body["error"] == {"code": code, "message": "details here"}
    assert [h["service"] for h in body["trace"]] == ["gateway", "lobby"]


def test_normalizes_fastapi_detail_errors(make_client):
    def handler(req):
        return httpx.Response(401, json={"detail": "Missing bearer token"})
    body = make_client(handler).get("/api/game/rooms/WOLF/state").json()
    assert body["error"] == {"code": "INVALID_TOKEN", "message": "Missing bearer token"}


def test_connection_refused_returns_503(make_client):
    def handler(req):
        raise httpx.ConnectError("refused", request=req)
    r = make_client(handler).get("/api/game/rooms/WOLF/state")
    assert r.status_code == 503
    body = r.json()
    assert body["ok"] is False and body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert body["trace"][0]["service"] == "gateway"


def test_timeout_returns_503(make_client):
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)
    r = make_client(handler).get("/api/chat/rooms/WOLF/messages")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_unknown_api_prefix_returns_404_envelope(make_client):
    r = make_client(lambda req: httpx.Response(500)).get("/api/redis/keys")
    assert r.status_code == 404 and r.json()["ok"] is False


def test_static_assets_pass_through_untouched(make_client):
    seen = {}
    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, content=b"console.log(1)", headers={"content-type": "application/javascript"})
    r = make_client(handler).get("/assets/index-abc.js")
    assert seen["url"] == f"{gateway.FRONTEND_URL}/assets/index-abc.js"
    assert r.content == b"console.log(1)"
    assert r.headers["content-type"].startswith("application/javascript")


def test_health_envelope(make_client):
    body = make_client(lambda req: httpx.Response(500)).get("/health/ready").json()
    assert body["ok"] is True and body["trace"][0]["service"] == "gateway"
