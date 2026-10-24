"""
Unit tests for the Chat Service (channel permissions, envelopes, auth).

Follows specifications from:
  - docs/roles/05-role-chat-statestore-qa.md (section 2.2)
  - contracts/api-contract.md (section 5.3)
"""
import importlib.util
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.state_store import InMemoryStateStore

# Every service is packaged as `app`, so load chat under its own module name to
# avoid colliding with the GameMaster tests that import `app` in the same session.
_spec = importlib.util.spec_from_file_location("chat_service_main", ROOT / "services" / "chat" / "app" / "main.py")
chat_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_main)

ROOM = "WOLF"
PLAYERS = {
    "wolf": {"player_id": "wolf", "name": "Wolfie", "role": "WEREWOLF", "alive": True, "is_host": True},
    "seer": {"player_id": "seer", "name": "Sally", "role": "SEER", "alive": True, "is_host": False},
    "ghost": {"player_id": "ghost", "name": "Gus", "role": "VILLAGER", "alive": False, "is_host": False},
    "deadwolf": {"player_id": "deadwolf", "name": "Rex", "role": "WEREWOLF", "alive": False, "is_host": False},
}


async def setup_room(phase: str = "DAY") -> InMemoryStateStore:
    store = InMemoryStateStore()
    chat_main.store = store
    await store.create_room(ROOM, {"room_id": ROOM, "phase": phase, "players": PLAYERS})
    for player_id in PLAYERS:
        await store.create_player_session(f"tok-{player_id}", {"room_id": ROOM, "player_id": player_id})
    return store


def auth(player_id: str) -> dict:
    return {"Authorization": f"Bearer tok-{player_id}"}


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=chat_main.app)
    async with AsyncClient(transport=transport, base_url="http://chat") as c:
        yield c


async def post(client, player_id, channel, text="hello", room=ROOM):
    return await client.post(f"/api/chat/rooms/{room}/messages", json={"channel": channel, "text": text},
                             headers=auth(player_id))


async def visible_channels(client, player_id):
    resp = await client.get(f"/api/chat/rooms/{ROOM}/messages", headers=auth(player_id))
    assert resp.status_code == 200
    return [m["channel"] for m in resp.json()["data"]["messages"]]


async def seed_all_channels(store):
    for channel in ("PUBLIC", "WOLF", "DEAD"):
        await store.append_chat(ROOM, {"channel": channel, "sender_id": "x", "sender_name": "X", "text": channel})


# ---------------------------------------------------------------------------
# 1. Posting permissions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("phase, player, channel, expected", [
    ("DAY", "seer", "PUBLIC", 200),
    ("DAY", "wolf", "PUBLIC", 200),
    ("DAY", "ghost", "PUBLIC", 403),     # dead players cannot talk in public
    ("NIGHT", "seer", "PUBLIC", 403),    # public chat is day-only
    ("WAITING", "seer", "PUBLIC", 403),
    ("NIGHT", "wolf", "WOLF", 200),
    ("NIGHT", "seer", "WOLF", 403),      # non-wolves cannot use wolf chat
    ("NIGHT", "deadwolf", "WOLF", 403),  # dead wolves lose wolf chat
    ("DAY", "wolf", "WOLF", 403),        # wolf chat is night-only
    ("DAY", "ghost", "DEAD", 200),
    ("NIGHT", "deadwolf", "DEAD", 200),
    ("DAY", "seer", "DEAD", 403),        # living players cannot use dead chat
])
async def test_post_permissions(client, phase, player, channel, expected):
    await setup_room(phase)
    resp = await post(client, player, channel)
    assert resp.status_code == expected
    if expected == 403:
        assert resp.json()["error"]["code"] == "FORBIDDEN_CHANNEL"


@pytest.mark.asyncio
async def test_post_success_envelope_matches_contract(client):
    store = await setup_room("DAY")
    resp = await client.post(f"/api/chat/rooms/{ROOM}/messages", json={"channel": "PUBLIC", "text": "  hi all  "},
                             headers={**auth("seer"), "X-Request-ID": "req-abc"})
    body = resp.json()
    assert body["ok"] is True
    assert body["data"] == {"message_id": 1, "status": "DELIVERED"}
    assert body["request_id"] == "req-abc"
    assert body["trace"][0]["service"] == "chat"

    stored = (await store.get_chat(ROOM))[0]
    assert stored["text"] == "hi all"
    assert stored["sender_id"] == "seer"
    assert stored["sender_name"] == "Sally"


# ---------------------------------------------------------------------------
# 2. Reading permissions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("player, expected", [
    ("seer", ["PUBLIC"]),
    ("wolf", ["PUBLIC", "WOLF"]),
    ("ghost", ["PUBLIC", "DEAD"]),
    ("deadwolf", ["PUBLIC", "DEAD"]),
])
async def test_read_filters_by_channel_permission(client, player, expected):
    store = await setup_room("NIGHT")
    await seed_all_channels(store)
    assert await visible_channels(client, player) == expected


@pytest.mark.asyncio
async def test_read_after_id_returns_only_newer_messages(client):
    store = await setup_room("DAY")
    for i in range(3):
        await store.append_chat(ROOM, {"channel": "PUBLIC", "sender_id": "x", "sender_name": "X", "text": f"m{i}"})
    resp = await client.get(f"/api/chat/rooms/{ROOM}/messages?after_id=1", headers=auth("seer"))
    assert [m["message_id"] for m in resp.json()["data"]["messages"]] == [2, 3]


@pytest.mark.asyncio
async def test_hidden_messages_do_not_starve_the_limit(client):
    # 5 wolf messages followed by 1 public one: a seer asking for limit=2 must still get the public one
    store = await setup_room("NIGHT")
    for i in range(5):
        await store.append_chat(ROOM, {"channel": "WOLF", "sender_id": "wolf", "sender_name": "W", "text": f"w{i}"})
    await store.append_chat(ROOM, {"channel": "PUBLIC", "sender_id": "x", "sender_name": "X", "text": "pub"})
    resp = await client.get(f"/api/chat/rooms/{ROOM}/messages?limit=2", headers=auth("seer"))
    assert [m["text"] for m in resp.json()["data"]["messages"]] == ["pub"]


# ---------------------------------------------------------------------------
# 3. Auth & validation errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_token(client):
    await setup_room()
    resp = await client.get(f"/api/chat/rooms/{ROOM}/messages")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "MISSING_TOKEN"


@pytest.mark.asyncio
async def test_invalid_token(client):
    await setup_room()
    resp = await client.get(f"/api/chat/rooms/{ROOM}/messages", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_token_for_another_room_is_rejected(client):
    store = await setup_room()
    await store.create_room("OTHR", {"room_id": "OTHR", "phase": "DAY", "players": {}})
    resp = await post(client, "seer", "PUBLIC", room="OTHR")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_session_for_deleted_room_returns_404(client):
    store = await setup_room()
    await store.create_player_session("tok-orphan", {"room_id": "GONE", "player_id": "p1"})
    resp = await client.get("/api/chat/rooms/GONE/messages", headers={"Authorization": "Bearer tok-orphan"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ROOM_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"channel": "PUBLIC", "text": "   "},
    {"channel": "PUBLIC", "text": "x" * 501},
    {"channel": "SECRET", "text": "hi"},
    {"text": "hi"},
])
async def test_invalid_payload_returns_400_envelope(client, body):
    await setup_room("DAY")
    resp = await client.post(f"/api/chat/rooms/{ROOM}/messages", json=body, headers=auth("seer"))
    assert resp.status_code == 400
    assert resp.json()["ok"] is False
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# 4. Health probes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_probes(client):
    await setup_room()
    assert (await client.get("/health/live")).status_code == 200
    assert (await client.get("/health/ready")).status_code == 200


@pytest.mark.asyncio
async def test_ready_probe_fails_when_store_is_down(client, monkeypatch):
    await setup_room()

    async def broken(room_id):
        raise ConnectionError("redis down")

    monkeypatch.setattr(chat_main.store, "get_room", broken)
    resp = await client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "DOWN"
