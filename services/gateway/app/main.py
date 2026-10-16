"""
Werewolf Gateway Service.

Stateless async reverse proxy and the single client-facing entrypoint.
- Generates a request ID per inbound request and propagates it as X-Request-ID.
- Wraps every API response in the standard envelope and prepends its own
  Downward API hop to the upstream trace array (contracts/api-contract.md §1-2).
- Proxies non-API GETs (SPA shell, /assets/*) to the frontend untouched.
"""
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from common.trace import get_service_trace

LOBBY_URL = os.getenv("LOBBY_URL", "http://localhost:8001")
GAMEMASTER_URL = os.getenv("GAMEMASTER_URL", "http://localhost:8002")
CHAT_URL = os.getenv("CHAT_URL", "http://localhost:8003")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
UPSTREAM_TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "5.0"))

SERVICE_NAME = "gateway"
REQUEST_ID_HEADER = "X-Request-ID"
# Optional header a backend may use to report its hop(s) instead of the JSON body.
TRACE_HEADER = "X-Trace"

API_ROUTES = {
    "lobby": LOBBY_URL,
    "game": GAMEMASTER_URL,
    "chat": CHAT_URL,
}
API_SERVICE_NAMES = {"lobby": "lobby", "game": "gamemaster", "chat": "chat"}

# Hop-by-hop headers (RFC 7230 §6.1) plus headers httpx/uvicorn recompute.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
    "content-encoding",
}

STATUS_TO_CODE = {
    400: "INVALID_REQUEST",
    401: "INVALID_TOKEN",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "INVALID_REQUEST",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
    504: "SERVICE_UNAVAILABLE",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT)
    try:
        yield
    finally:
        await app.state.client.aclose()


app = FastAPI(title="Werewolf Gateway Service", lifespan=lifespan)


def new_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:8]}"


def gateway_hop() -> Dict[str, str]:
    return get_service_trace(SERVICE_NAME)


def envelope_response(
    status_code: int,
    request_id: str,
    trace: List[Dict[str, Any]],
    data: Any = None,
    error: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    body: Dict[str, Any] = {"ok": error is None, "request_id": request_id, "trace": trace}
    if error is None:
        body["data"] = data
    else:
        body["error"] = error
    return JSONResponse(status_code=status_code, content=body, headers={REQUEST_ID_HEADER: request_id})


def forward_headers(request: Request, request_id: str) -> Dict[str, str]:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    headers[REQUEST_ID_HEADER] = request_id
    client_host = request.client.host if request.client else ""
    prior = request.headers.get("x-forwarded-for")
    headers["X-Forwarded-For"] = f"{prior}, {client_host}" if prior else client_host
    return headers


def parse_header_trace(resp: httpx.Response) -> List[Dict[str, Any]]:
    raw = resp.headers.get(TRACE_HEADER)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    if isinstance(parsed, dict):
        parsed = [parsed]
    return [h for h in parsed if isinstance(h, dict)] if isinstance(parsed, list) else []


def extract_upstream_trace(resp: httpx.Response, body: Any) -> List[Dict[str, Any]]:
    """Upstream hops in chronological order, from the JSON body or the X-Trace header."""
    trace: List[Dict[str, Any]] = []
    if isinstance(body, dict) and isinstance(body.get("trace"), list):
        trace = [h for h in body["trace"] if isinstance(h, dict)]
    if not trace:
        trace = parse_header_trace(resp)
    # Never double-count ourselves if a backend echoed a gateway hop.
    return [h for h in trace if h.get("service") != SERVICE_NAME]


def normalize_error(status_code: int, body: Any) -> Dict[str, str]:
    """Coerce any upstream error shape (our envelope, FastAPI `detail`, plain text) into {code, message}."""
    default_code = STATUS_TO_CODE.get(status_code, "UPSTREAM_ERROR")
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("code"):
            return {"code": str(err["code"]), "message": str(err.get("message", ""))}
        detail = body.get("detail")
        if isinstance(detail, dict) and detail.get("code"):
            return {"code": str(detail["code"]), "message": str(detail.get("message", ""))}
        if detail is not None:
            message = detail if isinstance(detail, str) else json.dumps(detail)
            return {"code": default_code, "message": message}
    return {"code": default_code, "message": f"Upstream returned HTTP {status_code}"}


async def proxy_api(request: Request, target_base: str, service_name: str) -> Response:
    request_id = new_request_id()
    url = f"{target_base}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"

    try:
        resp = await request.app.state.client.request(
            method=request.method,
            url=url,
            headers=forward_headers(request, request_id),
            content=await request.body(),
        )
    except httpx.TimeoutException:
        return envelope_response(
            503, request_id, [gateway_hop()],
            error={"code": "SERVICE_UNAVAILABLE", "message": f"Service '{service_name}' timed out"},
        )
    except httpx.RequestError as exc:
        return envelope_response(
            503, request_id, [gateway_hop()],
            error={"code": "SERVICE_UNAVAILABLE", "message": f"Service '{service_name}' unreachable: {exc.__class__.__name__}"},
        )

    try:
        body = resp.json()
    except ValueError:
        body = None

    trace = [gateway_hop(), *extract_upstream_trace(resp, body)]

    if resp.is_success:
        data = body.get("data") if isinstance(body, dict) and "data" in body else body
        return envelope_response(resp.status_code, request_id, trace, data=data)

    return envelope_response(resp.status_code, request_id, trace, error=normalize_error(resp.status_code, body))


@app.get("/health/live")
@app.get("/health/ready")
async def health():
    request_id = new_request_id()
    return envelope_response(200, request_id, [gateway_hop()], data={"status": "UP", "service": SERVICE_NAME})


@app.api_route("/api/{service}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def route_api(request: Request, service: str, path: str):
    target = API_ROUTES.get(service)
    if target is None:
        return envelope_response(
            404, new_request_id(), [gateway_hop()],
            error={"code": "NOT_FOUND", "message": f"No API route for '/api/{service}'"},
        )
    return await proxy_api(request, target, API_SERVICE_NAMES[service])


@app.get("/{path:path}")
async def route_frontend(request: Request, path: str):
    """Static SPA passthrough. No envelope: HTML/JS/CSS bytes go through untouched."""
    request_id = new_request_id()
    url = f"{FRONTEND_URL}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    try:
        resp = await request.app.state.client.get(url, headers=forward_headers(request, request_id))
    except httpx.RequestError:
        return envelope_response(
            503, request_id, [gateway_hop()],
            error={"code": "SERVICE_UNAVAILABLE", "message": "Service 'frontend' unreachable"},
        )
    headers = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP}
    headers[REQUEST_ID_HEADER] = request_id
    return Response(content=resp.content, status_code=resp.status_code, headers=headers)
