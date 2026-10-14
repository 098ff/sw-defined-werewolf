import argparse
import asyncio
import os
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from tests.mocks.fixtures import SCENARIOS

app = FastAPI(title="Mock Backend Unified Server")

current_scenario = "standard_night"
chat_messages = [
    {"message_id": 1, "channel": "PUBLIC", "sender_id": "p1", "sender_name": "Alice", "text": "Hello everyone!", "created_at": 1720000000},
    {"message_id": 2, "channel": "PUBLIC", "sender_id": "p2", "sender_name": "Bob", "text": "Who do you think is suspicious?", "created_at": 1720000010}
]

@app.get("/health/live")
@app.get("/health/ready")
async def health():
    return {"ok": True, "status": "UP", "service": "mock-backend"}

@app.get("/mock/list-scenarios")
async def list_scenarios():
    return {"scenarios": list(SCENARIOS.keys()), "current": current_scenario}

@app.post("/mock/set-scenario")
async def set_scenario(name: str = Query(...)):
    global current_scenario
    if name not in SCENARIOS and name not in ["lobby_waiting", "lobby_full"]:
        raise HTTPException(status_code=400, detail="Unknown scenario")
    current_scenario = name
    return {"ok": True, "current_scenario": current_scenario}

# --- Lobby Endpoints ---
@app.post("/api/lobby/rooms")
async def create_room(payload: dict):
    return {
        "ok": True,
        "data": {
            "room_id": "WOLF",
            "player_id": "p1",
            "player_token": "mock-token-p1",
            "is_host": True
        },
        "request_id": "mock-req",
        "trace": [{"service": "lobby", "pod": "mock-lobby", "node": "pi-02"}]
    }

@app.post("/api/lobby/rooms/{room_id}/join")
async def join_room(room_id: str, payload: dict):
    return {
        "ok": True,
        "data": {
            "room_id": room_id,
            "player_id": "p2",
            "player_token": "mock-token-p2",
            "is_host": False
        },
        "request_id": "mock-req",
        "trace": [{"service": "lobby", "pod": "mock-lobby", "node": "pi-02"}]
    }

@app.get("/api/lobby/rooms/{room_id}")
async def get_lobby(room_id: str):
    return {
        "ok": True,
        "data": {
            "room_id": room_id,
            "phase": "WAITING",
            "host_player_id": "p1",
            "players": [
                {"player_id": "p1", "name": "Alice", "is_host": True},
                {"player_id": "p2", "name": "Bob", "is_host": False},
                {"player_id": "p3", "name": "Carol", "is_host": False},
                {"player_id": "p4", "name": "Dave", "is_host": False},
                {"player_id": "p5", "name": "Eve", "is_host": False}
            ]
        },
        "request_id": "mock-req",
        "trace": [{"service": "lobby", "pod": "mock-lobby", "node": "pi-02"}]
    }

@app.post("/api/lobby/rooms/{room_id}/start")
async def start_game(room_id: str):
    return {
        "ok": True,
        "data": {"status": "STARTED"},
        "request_id": "mock-req",
        "trace": [{"service": "lobby", "pod": "mock-lobby", "node": "pi-02"}]
    }

# --- GameMaster Endpoints ---
@app.get("/api/game/rooms/{room_id}/state")
async def get_game_state(room_id: str):
    data = SCENARIOS.get(current_scenario, SCENARIOS["standard_night"]).copy()
    data["room_id"] = room_id
    return {
        "ok": True,
        "data": data,
        "request_id": "mock-req",
        "trace": [{"service": "gamemaster", "pod": "mock-gm", "node": "pi-04"}]
    }

@app.post("/api/game/rooms/{room_id}/night-actions")
async def night_action(room_id: str, payload: dict):
    return {
        "ok": True,
        "data": {"status": "ACCEPTED", "target": payload.get("target_id")},
        "request_id": "mock-req",
        "trace": [{"service": "gamemaster", "pod": "mock-gm", "node": "pi-04"}]
    }

@app.post("/api/game/rooms/{room_id}/vote")
async def vote(room_id: str, payload: dict):
    return {
        "ok": True,
        "data": {"status": "VOTE_CAST", "target": payload.get("target_id")},
        "request_id": "mock-req",
        "trace": [{"service": "gamemaster", "pod": "mock-gm", "node": "pi-04"}]
    }

# --- Chat Endpoints ---
@app.get("/api/chat/rooms/{room_id}/messages")
async def get_chat(room_id: str, after_id: int = 0):
    filtered = [m for m in chat_messages if m["message_id"] > after_id]
    return {
        "ok": True,
        "data": {"messages": filtered},
        "request_id": "mock-req",
        "trace": [{"service": "chat", "pod": "mock-chat", "node": "pi-05"}]
    }

@app.post("/api/chat/rooms/{room_id}/messages")
async def send_chat(room_id: str, payload: dict):
    new_msg = {
        "message_id": len(chat_messages) + 1,
        "channel": payload.get("channel", "PUBLIC"),
        "sender_id": "p1",
        "sender_name": "Alice",
        "text": payload.get("text", ""),
        "created_at": 1720000020
    }
    chat_messages.append(new_msg)
    return {
        "ok": True,
        "data": {"message_id": new_msg["message_id"], "status": "DELIVERED"},
        "request_id": "mock-req",
        "trace": [{"service": "chat", "pod": "mock-chat", "node": "pi-05"}]
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    print(f"Starting Mock Unified Backend on port {args.port}...")
    uvicorn.run(app, host="0.0.0.0", port=args.port)
