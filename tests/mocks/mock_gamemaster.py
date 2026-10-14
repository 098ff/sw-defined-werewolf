import argparse
import asyncio
import os
import uvicorn
from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.responses import JSONResponse
from tests.mocks.fixtures import SCENARIOS

app = FastAPI(title="Mock GameMaster Service")

# Default active scenario
active_scenario = "standard_night"

@app.get("/health/live")
@app.get("/health/ready")
async def health():
    return {"ok": True, "status": "UP", "service": "mock-gamemaster"}

@app.post("/mock/set-scenario")
async def set_scenario(name: str = Query(...)):
    global active_scenario
    if name not in SCENARIOS and name not in ["lobby_under_capacity", "game_already_started", "slow_network", "server_error_500"]:
        raise HTTPException(status_code=400, detail=f"Unknown scenario {name}")
    active_scenario = name
    return {"ok": True, "active_scenario": active_scenario}

@app.post("/internal/rooms/{room_id}/initialize")
async def initialize(room_id: str, scenario: str = Query(None)):
    scen = scenario or active_scenario
    if scen == "lobby_under_capacity":
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": {"code": "INVALID_REQUEST", "message": "At least 4 players required to start"}, "request_id": "mock-req", "trace": []}
        )
    if scen == "game_already_started":
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": {"code": "GAME_ALREADY_STARTED", "message": "Room already in progress"}, "request_id": "mock-req", "trace": []}
        )
    return {
        "ok": True,
        "data": {"status": "INITIALIZED", "room_id": room_id},
        "request_id": "mock-req",
        "trace": [{"service": "gamemaster", "pod": "mock-gm", "node": "node-mock"}]
    }

@app.get("/api/game/rooms/{room_id}/state")
async def get_state(room_id: str, scenario: str = Query(None)):
    scen = scenario or active_scenario

    if scen == "slow_network":
        await asyncio.sleep(2.5)

    if scen == "server_error_500":
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": {"code": "INTERNAL_SERVER_ERROR", "message": "Simulated unhandled exception"}, "request_id": "mock-req", "trace": []}
        )

    data = SCENARIOS.get(scen, SCENARIOS["standard_night"]).copy()
    data["room_id"] = room_id

    return {
        "ok": True,
        "data": data,
        "request_id": "mock-req",
        "trace": [{"service": "gamemaster", "pod": "mock-gm", "node": "node-mock"}]
    }

@app.post("/api/game/rooms/{room_id}/night-actions")
async def night_actions(room_id: str, payload: dict):
    if active_scenario == "action_conflict":
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": {"code": "ACTION_ALREADY_SUBMITTED", "message": "Cannot alter action after submission"}, "request_id": "mock-req", "trace": []}
        )
    return {
        "ok": True,
        "data": {"status": "ACCEPTED", "action": payload.get("action")},
        "request_id": "mock-req",
        "trace": [{"service": "gamemaster", "pod": "mock-gm", "node": "node-mock"}]
    }

@app.post("/api/game/rooms/{room_id}/vote")
async def vote(room_id: str, payload: dict):
    if active_scenario == "stale_phase_version":
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": {"code": "PHASE_VERSION_CONFLICT", "message": "Phase version expired"}, "request_id": "mock-req", "trace": []}
        )
    return {
        "ok": True,
        "data": {"status": "VOTE_CAST", "target_id": payload.get("target_id")},
        "request_id": "mock-req",
        "trace": [{"service": "gamemaster", "pod": "mock-gm", "node": "node-mock"}]
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    print(f"Starting Mock GameMaster Server on port {args.port}...")
    uvicorn.run(app, host="0.0.0.0", port=args.port)
