"""Lobby-only tests: in-memory storage fake and HTTP-mocked GameMaster."""

import asyncio
import re
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from common.state_store import InMemoryStateStore, StateConflictError
from services.lobby.app import main as lobby


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("POD_NAME", "lobby-test-pod")
    monkeypatch.setenv("NODE_NAME", "lobby-test-node")
    store = InMemoryStateStore()
    calls = []

    def initialize(request):
        calls.append(request)
        return httpx.Response(200, json={
            "ok": True, "data": {"status": "INITIALIZED"},
            "trace": [{"service": "gamemaster", "pod": "mock-gm", "node": "mock-node"}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(initialize)) as gm:
        app = lobby.create_app(store, gm, "http://mock-gamemaster")
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lobby") as client:
                yield client, store, gm, calls


def auth(player):
    return {"Authorization": f"Bearer {player['player_token']}"}


async def room_with_players(client, count=1):
    response = await client.post("/api/lobby/rooms", json={"name": "Host"})
    assert response.status_code == 200
    host = response.json()["data"]
    players = [host]
    for index in range(1, count):
        joined = await client.post(f"/api/lobby/rooms/{host['room_id']}/join", json={"name": f"Player {index}"})
        assert joined.status_code == 200
        players.append(joined.json()["data"])
    return host, players


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"ok", "error", "request_id", "trace"}
    assert body["ok"] is False
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["trace"][0] == {
        "service": "lobby", "pod": "lobby-test-pod", "node": "lobby-test-node",
    }


@pytest.mark.asyncio
async def test_create_join_and_public_view(env):
    client, store, _, calls = env
    created = await client.post("/api/lobby/rooms", json={"name": "  Alice  "})
    host = created.json()["data"]
    assert re.fullmatch("[A-Z]{4}", host["room_id"])
    assert host["is_host"] is True
    assert len(host["player_token"]) >= 32
    assert re.fullmatch("req-[a-f0-9]{32}", created.json()["request_id"])
    session = await store.get_player_session(host["player_token"])
    assert session["player_id"] == host["player_id"]
    assert session["room_id"] == host["room_id"]
    joined = await client.post(f"/api/lobby/rooms/{host['room_id']}/join", json={"name": "  Bob  "})
    guest = joined.json()["data"]
    assert guest["is_host"] is False
    assert guest["player_token"] != host["player_token"]
    assert guest["player_id"] != host["player_id"]
    assert (await store.get_player_session(guest["player_token"]))["player_id"] == guest["player_id"]
    response = await client.get(f"/api/lobby/rooms/{host['room_id']}", headers=auth(guest))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {
        "room_id": host["room_id"], "phase": "WAITING", "host_player_id": host["player_id"],
        "players": [
            {"player_id": host["player_id"], "name": "Alice", "is_host": True},
            {"player_id": guest["player_id"], "name": "Bob", "is_host": False},
        ],
    }
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "  "}, {"name": "A"},
                                     {"name": "A" * 21}, {"name": 123}, {"name": None}])
@pytest.mark.parametrize("operation", ["create", "join"])
async def test_invalid_names(env, payload, operation):
    client, _, _, _ = env
    host, _ = await room_with_players(client)
    path = "/api/lobby/rooms" if operation == "create" else f"/api/lobby/rooms/{host['room_id']}/join"
    assert_error(await client.post(path, json=payload), 400, "INVALID_REQUEST")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["Ab", "A" * 20])
async def test_name_length_boundaries(env, name):
    client, _, _, _ = env
    assert (await client.post("/api/lobby/rooms", json={"name": name})).status_code == 200


@pytest.mark.asyncio
async def test_malformed_json_and_unmatched_route(env):
    client, _, _, _ = env
    response = await client.post("/api/lobby/rooms", content="{", headers={"Content-Type": "application/json"})
    assert_error(response, 400, "INVALID_REQUEST")
    assert_error(await client.get("/not-a-route"), 404, "INVALID_REQUEST")


@pytest.mark.asyncio
async def test_room_code_collision_retries_without_overwriting(env, monkeypatch):
    client, store, _, _ = env
    codes = iter(["WOLF", "WOLF", "MOON"])
    monkeypatch.setattr(lobby, "generate_room_code", lambda: next(codes))
    first, _ = await room_with_players(client)
    second, _ = await room_with_players(client)
    assert first["room_id"] == "WOLF"
    assert second["room_id"] == "MOON"
    assert (await store.get_room("WOLF"))["host_player_id"] == first["player_id"]


@pytest.mark.asyncio
async def test_room_code_collision_exhaustion(env, monkeypatch):
    client, _, _, _ = env
    monkeypatch.setattr(lobby, "generate_room_code", lambda: "WOLF")
    await room_with_players(client)
    assert_error(await client.post("/api/lobby/rooms", json={"name": "Other"}), 503, "SERVICE_UNAVAILABLE")


@pytest.mark.asyncio
async def test_join_full_missing_and_duplicate_name(env):
    client, store, _, _ = env
    host, _ = await room_with_players(client)
    room_id = host["room_id"]
    assert_error(await client.post(f"/api/lobby/rooms/{room_id}/join", json={"name": " hOsT "}), 400, "INVALID_REQUEST")
    assert_error(await client.post("/api/lobby/rooms/NONE/join", json={"name": "Bob"}), 404, "ROOM_NOT_FOUND")
    for i in range(5):
        assert (await client.post(f"/api/lobby/rooms/{room_id}/join", json={"name": f"Guest {i}"})).status_code == 200
    assert_error(await client.post(f"/api/lobby/rooms/{room_id}/join", json={"name": "Seventh"}), 409, "ROOM_FULL")
    assert len((await store.get_room(room_id))["players"]) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["NIGHT", "DAY", "ENDED"])
async def test_join_and_start_reject_started_room(env, phase):
    client, store, _, calls = env
    host, _ = await room_with_players(client, 4)
    await store.update_room(host["room_id"], lambda state: {**state, "phase": phase})
    assert_error(await client.post(f"/api/lobby/rooms/{host['room_id']}/join", json={"name": "Late"}), 409, "GAME_ALREADY_STARTED")
    assert_error(await client.post(f"/api/lobby/rooms/{host['room_id']}/start", headers=auth(host)), 409, "GAME_ALREADY_STARTED")
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["view", "start"])
@pytest.mark.parametrize("header,code", [(None, "MISSING_TOKEN"), ("Basic abc", "INVALID_TOKEN"),
                                        ("Bearer", "INVALID_TOKEN"), ("Bearer unknown", "INVALID_TOKEN"),
                                        ("Bearer a b", "INVALID_TOKEN")])
async def test_authentication_errors(env, operation, header, code):
    client, _, _, calls = env
    host, _ = await room_with_players(client, 4)
    path = f"/api/lobby/rooms/{host['room_id']}"
    headers = {} if header is None else {"Authorization": header}
    response = await client.get(path, headers=headers) if operation == "view" else await client.post(path + "/start", headers=headers)
    assert_error(response, 401, code)
    assert calls == []


@pytest.mark.asyncio
async def test_other_room_token_cannot_view_or_start(env):
    client, _, _, _ = env
    first, _ = await room_with_players(client, 4)
    second, _ = await room_with_players(client)
    path = f"/api/lobby/rooms/{first['room_id']}"
    assert_error(await client.get(path, headers=auth(second)), 401, "INVALID_TOKEN")
    assert_error(await client.post(path + "/start", headers=auth(second)), 401, "INVALID_TOKEN")


@pytest.mark.asyncio
async def test_authority_comes_from_room_not_session_or_query(env):
    client, store, _, calls = env
    host, players = await room_with_players(client, 4)
    guest = players[1]
    await store.create_player_session(guest["player_token"], {
        "room_id": host["room_id"], "player_id": guest["player_id"], "is_host": True,
    })
    response = await client.post(f"/api/lobby/rooms/{host['room_id']}/start", headers=auth(guest),
                                 params={"player_id": host["player_id"]})
    assert_error(response, 403, "HOST_ONLY")
    assert calls == []


@pytest.mark.asyncio
async def test_removed_player_session_and_missing_room(env):
    client, store, _, _ = env
    host, _ = await room_with_players(client)
    await store.create_player_session("orphan", {"room_id": host["room_id"], "player_id": "removed"})
    assert_error(await client.get(f"/api/lobby/rooms/{host['room_id']}", headers={"Authorization": "Bearer orphan"}), 401, "INVALID_TOKEN")
    await store.create_player_session("expired-room", {"room_id": "NONE", "player_id": "p1"})
    assert_error(await client.get("/api/lobby/rooms/NONE", headers={"Authorization": "Bearer expired-room"}), 404, "ROOM_NOT_FOUND")


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 6])
async def test_start_player_count_and_handoff(env, count):
    client, store, _, calls = env
    host, _ = await room_with_players(client, count)
    response = await client.post(f"/api/lobby/rooms/{host['room_id']}/start", headers={**auth(host), "X-Request-ID": "req-handoff"})
    if count < 4:
        assert_error(response, 400, "INVALID_REQUEST")
        assert response.json()["error"]["message"] == "At least 4 players required to start"
        assert calls == []
    else:
        assert response.status_code == 200
        assert response.json()["data"] == {"status": "STARTED"}
        assert response.json()["request_id"] == "req-handoff"
        assert [hop["service"] for hop in response.json()["trace"]] == ["lobby", "gamemaster"]
        assert len(calls) == 1
        assert str(calls[0].url) == f"http://mock-gamemaster/internal/rooms/{host['room_id']}/initialize"
        assert calls[0].headers["X-Request-ID"] == "req-handoff"
        # A mock acknowledgement must not make Lobby assign roles or advance the phase.
        room = await store.get_room(host["room_id"])
        assert room["phase"] == "WAITING"
        assert all(p["role"] is None for p in room["players"].values())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "connect", "html", "list", "server", "false-success", "bad-error"])
async def test_gamemaster_failures_are_safe_and_not_retried(env, failure):
    client, _, gm, _ = env
    host, _ = await room_with_players(client, 4)
    if failure in {"timeout", "connect"}:
        error_type = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
        gm.post = AsyncMock(side_effect=error_type("secret upstream details"))
    else:
        replies = {
            "html": httpx.Response(502, text="<html>secret</html>"),
            "list": httpx.Response(200, json=[]),
            "server": httpx.Response(500, json={"error": {"code": "INTERNAL", "message": "secret"}}),
            "false-success": httpx.Response(200, json={"ok": False}),
            "bad-error": httpx.Response(409, json={"error": "secret"}),
        }
        gm.post = AsyncMock(return_value=replies[failure])
    response = await client.post(f"/api/lobby/rooms/{host['room_id']}/start", headers=auth(host))
    assert_error(response, 503, "SERVICE_UNAVAILABLE")
    assert "secret" not in response.text
    gm.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_gamemaster_error_preserves_error_and_lobby_identity(env):
    client, _, gm, _ = env
    host, _ = await room_with_players(client, 4)
    gm.post = AsyncMock(return_value=httpx.Response(409, json={
        "ok": False, "error": {"code": "GAME_ALREADY_STARTED", "message": "Already initialized"},
        "request_id": "wrong-upstream-id", "trace": [],
    }))
    response = await client.post(f"/api/lobby/rooms/{host['room_id']}/start", headers={**auth(host), "X-Request-ID": "req-original"})
    assert_error(response, 409, "GAME_ALREADY_STARTED")
    assert response.json()["request_id"] == "req-original"


@pytest.mark.asyncio
@pytest.mark.parametrize("same_name", [False, True])
async def test_concurrent_joins_revalidate_latest_state(env, same_name):
    client, store, _, _ = env
    host, _ = await room_with_players(client, 5 if not same_name else 1)
    original_get = store.get_room
    gate = asyncio.Event()
    arrived = 0

    async def simultaneous_read(room_id):
        nonlocal arrived
        snapshot = await original_get(room_id)
        arrived += 1
        if arrived == 2:
            gate.set()
        await gate.wait()
        return snapshot

    store.get_room = simultaneous_read
    path = f"/api/lobby/rooms/{host['room_id']}/join"
    responses = await asyncio.gather(
        client.post(path, json={"name": "Last guest"}),
        client.post(path, json={"name": "last GUEST" if same_name else "Other guest"}),
    )
    assert sorted(r.status_code for r in responses) == ([200, 400] if same_name else [200, 409])
    assert len((await original_get(host["room_id"]))["players"]) == (2 if same_name else 6)


@pytest.mark.asyncio
async def test_phase_change_between_join_read_and_write(env):
    client, store, _, _ = env
    host, _ = await room_with_players(client)
    original_update = store.update_room

    async def start_before_join(room_id, mutator):
        await original_update(room_id, lambda state: {**state, "phase": "NIGHT"})
        return await original_update(room_id, mutator)

    store.update_room = start_before_join
    assert_error(await client.post(f"/api/lobby/rooms/{host['room_id']}/join", json={"name": "Late guest"}), 409, "GAME_ALREADY_STARTED")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,status,code", [
    (StateConflictError("private detail"), 409, "STATE_CONFLICT"),
    (RedisConnectionError("private detail"), 503, "STATE_STORE_UNAVAILABLE"),
    (RedisTimeoutError("private detail"), 503, "STATE_STORE_UNAVAILABLE"),
    (ValueError("expired room"), 404, "ROOM_NOT_FOUND"),
])
async def test_storage_write_failures(env, failure, status, code):
    client, store, _, _ = env
    host, _ = await room_with_players(client)
    store.update_room = AsyncMock(side_effect=failure)
    store.create_player_session = AsyncMock()
    response = await client.post(f"/api/lobby/rooms/{host['room_id']}/join", json={"name": "Guest"})
    assert_error(response, status, code)
    assert "private detail" not in response.text
    store.create_player_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_readiness_checks_storage_but_liveness_does_not(env):
    client, store, _, _ = env
    assert (await client.get("/health/ready")).status_code == 200
    store.get_room = AsyncMock(side_effect=RedisConnectionError("private details"))
    assert_error(await client.get("/health/ready"), 503, "STATE_STORE_UNAVAILABLE")
    live = await client.get("/health/live")
    assert live.status_code == 200
    assert live.json()["data"] == {"status": "UP", "service": "lobby"}
    assert store.get_room.await_count == 1


@pytest.mark.asyncio
async def test_private_room_data_not_returned_even_after_start(env):
    client, store, _, _ = env
    host, _ = await room_with_players(client)

    def private_state(state):
        state["phase"] = "NIGHT"
        state["players"][host["player_id"]]["role"] = "WEREWOLF"
        state["night_actions"] = {"secret": "private"}
        return state

    await store.update_room(host["room_id"], private_state)
    response = await client.get(f"/api/lobby/rooms/{host['room_id']}", headers=auth(host))
    assert response.status_code == 200
    assert "WEREWOLF" not in response.text
    assert "night_actions" not in response.text
    assert host["player_token"] not in response.text


@pytest.mark.asyncio
async def test_guest_leave_removes_player_and_revokes_token(env):
    client, _, _, _ = env
    host, players = await room_with_players(client, 3)
    guest = players[1]
    path = f"/api/lobby/rooms/{host['room_id']}"
    left = await client.post(path + "/leave", headers=auth(guest))
    assert left.status_code == 200
    assert left.json()["data"] == {"status": "LEFT"}
    view = (await client.get(path, headers=auth(host))).json()["data"]
    assert guest["player_id"] not in [p["player_id"] for p in view["players"]]
    assert view["host_player_id"] == host["player_id"]
    assert_error(await client.get(path, headers=auth(guest)), 401, "INVALID_TOKEN")
    assert_error(await client.post(path + "/leave", headers=auth(guest)), 401, "INVALID_TOKEN")
    rejoined = await client.post(path + "/join", json={"name": "Player 1"})
    assert rejoined.status_code == 200


@pytest.mark.asyncio
async def test_host_leave_transfers_host_to_next_player(env):
    client, _, _, _ = env
    host, players = await room_with_players(client, 3)
    path = f"/api/lobby/rooms/{host['room_id']}"
    assert (await client.post(path + "/leave", headers=auth(host))).status_code == 200
    view = (await client.get(path, headers=auth(players[1]))).json()["data"]
    assert view["host_player_id"] == players[1]["player_id"]
    assert [p["is_host"] for p in view["players"]] == [True, False]
    assert_error(await client.post(path + "/start", headers=auth(players[2])), 403, "HOST_ONLY")


@pytest.mark.asyncio
async def test_last_player_leave_empties_room(env):
    client, store, _, _ = env
    host, _ = await room_with_players(client)
    assert (await client.post(f"/api/lobby/rooms/{host['room_id']}/leave", headers=auth(host))).status_code == 200
    assert (await store.get_room(host["room_id"]))["players"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["NIGHT", "DAY", "ENDED"])
async def test_leave_rejected_after_game_started(env, phase):
    client, store, _, _ = env
    host, players = await room_with_players(client, 4)
    await store.update_room(host["room_id"], lambda state: {**state, "phase": phase})
    assert_error(await client.post(f"/api/lobby/rooms/{host['room_id']}/leave", headers=auth(players[1])),
                 409, "GAME_ALREADY_STARTED")
    assert len((await store.get_room(host["room_id"]))["players"]) == 4


@pytest.mark.asyncio
async def test_leave_requires_valid_token(env):
    client, _, _, _ = env
    host, _ = await room_with_players(client)
    other, _ = await room_with_players(client)
    path = f"/api/lobby/rooms/{host['room_id']}/leave"
    assert_error(await client.post(path), 401, "MISSING_TOKEN")
    assert_error(await client.post(path, headers=auth(other)), 401, "INVALID_TOKEN")
