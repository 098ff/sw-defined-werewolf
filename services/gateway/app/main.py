import os
import uuid
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from common.trace import get_service_trace

app = FastAPI(title="Werewolf Gateway Service")

LOBBY_URL = os.getenv("LOBBY_URL", "http://localhost:8001")
GAMEMASTER_URL = os.getenv("GAMEMASTER_URL", "http://localhost:8002")
CHAT_URL = os.getenv("CHAT_URL", "http://localhost:8003")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

client = httpx.AsyncClient(timeout=10.0)

@app.on_event("shutdown")
async def shutdown():
    await client.aclose()

@app.get("/health/live")
@app.get("/health/ready")
async def health():
    return {
        "ok": True,
        "status": "UP",
        "service": "gateway",
        "trace": [get_service_trace("gateway")]
    }

async def proxy_request(target_url: str, request: Request, service_name: str):
    request_id = request.headers.get("X-Request-ID", f"req-{uuid.uuid4().hex[:8]}")
    url = f"{target_url}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"

    headers = dict(request.headers)
    headers["X-Request-ID"] = request_id
    headers.pop("host", None)

    try:
        body = await request.body()
        resp = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=body
        )

        # Try to parse JSON and inject gateway trace
        try:
            data = resp.json()
            if isinstance(data, dict):
                data.setdefault("request_id", request_id)
                trace = data.get("trace", [])
                trace.insert(0, get_service_trace("gateway"))
                data["trace"] = trace
                return JSONResponse(status_code=resp.status_code, content=data)
        except Exception:
            pass

        return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))

    except httpx.RequestError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": {"code": "SERVICE_UNAVAILABLE", "message": f"Service {service_name} unavailable: {str(exc)}"},
                "request_id": request_id,
                "trace": [get_service_trace("gateway")]
            }
        )

@app.api_route("/api/lobby/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route_lobby(request: Request, path: str):
    return await proxy_request(LOBBY_URL, request, "lobby")

@app.api_route("/api/game/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route_gamemaster(request: Request, path: str):
    return await proxy_request(GAMEMASTER_URL, request, "gamemaster")

@app.api_route("/api/chat/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route_chat(request: Request, path: str):
    return await proxy_request(CHAT_URL, request, "chat")

@app.api_route("/{path:path}", methods=["GET"])
async def route_frontend(request: Request, path: str):
    # Proxy UI static assets and html to frontend service
    return await proxy_request(FRONTEND_URL, request, "frontend")
