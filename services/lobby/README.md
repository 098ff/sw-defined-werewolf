# Lobby Service

Handles room creation, joining, player lists, and host-authorized game starts. GameMaster assigns roles and changes the game phase.

## Features

- Creates a four-digit room code, such as `"0538"`, and makes the creator the host.
- Issues a `player_token` to each player for viewing the room and starting the game.
- Trims player names and requires 2–20 characters. Names must be unique within the room, ignoring case.
- Allows up to 6 players, including simultaneous joins, and accepts joins only during `WAITING`.
- Allows only the host to start a game with 4–6 players.
- Includes `request_id` and `trace` in success and error responses.

## Run locally

Use Python 3.11 or newer. Run all commands from the **repository root**.

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r services/lobby/requirements.txt
```

### 2. Start mock GameMaster in the first terminal

```bash
source .venv/bin/activate
python -m tests.mocks.mock_gamemaster --port 8002
```

### 3. Start Lobby in a second terminal

```bash
source .venv/bin/activate
STATE_STORE_BACKEND=in_memory GAMEMASTER_URL=http://localhost:8002 \
  python -m uvicorn services.lobby.app.main:app --reload --port 8001
```

Open **http://localhost:8001/docs** to explore the API and try requests through Swagger.

This mode does not require Redis. Data is stored in memory and disappears when Lobby restarts. Mock GameMaster acknowledges a successful start without changing the room state, so the phase remains `WAITING` after Start.

## API endpoints

| Method | Path | Purpose | Required token |
|---|---|---|---|
| `POST` | `/api/lobby/rooms` | Creates a room and makes the creator the host. | None |
| `POST` | `/api/lobby/rooms/{room_id}/join` | Adds a player to the room. | None |
| `GET` | `/api/lobby/rooms/{room_id}` | Returns the room code, phase, host, and player list without revealing roles. | A member of that room |
| `POST` | `/api/lobby/rooms/{room_id}/start` | Checks host permission and player count, then asks GameMaster to start the game. | The room's host |
| `GET` | `/health/live` | Checks whether Lobby can respond to requests. | None |
| `GET` | `/health/ready` | Checks whether Lobby can reach storage. | None |

`{room_id}` is the code returned when creating a room, such as `0538`. It is stored as a string to preserve leading zeros.

### Create a room

```bash
curl -X POST 'http://localhost:8001/api/lobby/rooms' \
  -H 'Content-Type: application/json' \
  -d '{"name":"Alice"}'
```

On success, the response contains these fields inside `data`:

```json
{
  "room_id": "0538",
  "player_id": "p-...",
  "player_token": "...",
  "is_host": true
}
```

Share `room_id` with other players so they can join. Keep each player's `player_token` private.

### Join a room

```bash
curl -X POST 'http://localhost:8001/api/lobby/rooms/0538/join' \
  -H 'Content-Type: application/json' \
  -d '{"name":"Bob"}'
```

Returns the same fields as room creation, with the new player's own `player_id` and `player_token`, and `is_host` set to `false`.

### View a room

Replace the room code and `YOUR_PLAYER_TOKEN` with actual values. Any member of the room can use their token:

```bash
curl 'http://localhost:8001/api/lobby/rooms/0538' \
  -H 'Authorization: Bearer YOUR_PLAYER_TOKEN'
```

Returns `room_id`, `phase`, `host_player_id`, and `players`. Each player entry includes their ID, name, and host status.

### Start a game

Once the room has 4–6 players, replace `YOUR_HOST_TOKEN` with the host's token. No request body is needed:

```bash
curl -X POST 'http://localhost:8001/api/lobby/rooms/0538/start' \
  -H 'Authorization: Bearer YOUR_HOST_TOKEN'
```

When GameMaster acknowledges initialization, the response contains `data: {"status":"STARTED"}`.

### Common errors

| HTTP | Error code | Meaning |
|---|---|---|
| `400` | `INVALID_REQUEST` | Invalid or duplicate name, or an invalid player count for starting. |
| `401` | `MISSING_TOKEN` / `INVALID_TOKEN` | Token is missing or invalid for this room. |
| `403` | `HOST_ONLY` | A player other than the host tried to start the game. |
| `404` | `ROOM_NOT_FOUND` | Room does not exist. |
| `409` | `ROOM_FULL` / `GAME_ALREADY_STARTED` | Room is full or the game has already started. |
| `503` | `SERVICE_UNAVAILABLE` / `STATE_STORE_UNAVAILABLE` | GameMaster or storage is unavailable. |

## Run unit tests

```bash
python -m pytest tests/unit/test_lobby.py -q
```

Tests cover Lobby only, using in-memory storage and a mocked GameMaster. No other servers are required. Coverage includes the main room flow, token and host checks, player counts, duplicate names, simultaneous joins, and dependency failures.
