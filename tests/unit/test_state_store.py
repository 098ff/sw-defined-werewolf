"""
StateStore contract tests: every test runs against both InMemoryStateStore and
RedisStateStore (backed by fakeredis), so the two implementations stay interchangeable.

Follows specifications from:
  - docs/roles/05-role-chat-statestore-qa.md
  - contracts/api-contract.md (section 4)
"""
import asyncio
import hashlib
import json
import time

import fakeredis
import pytest

from common.state_store import (
    CHAT_HISTORY_LIMIT,
    InMemoryStateStore,
    RedisStateStore,
    StateConflictError,
)


def make_redis_store() -> RedisStateStore:
    store = RedisStateStore("redis://unused:6379")
    store._redis = fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    return store


@pytest.fixture(params=["in_memory", "redis"])
def store(request):
    return InMemoryStateStore() if request.param == "in_memory" else make_redis_store()


def room_state(room_id: str = "WOLF") -> dict:
    return {"room_id": room_id, "phase": "DAY", "players": {}, "day_votes": {}}


# ---------------------------------------------------------------------------
# 1. Room lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_missing_room_returns_none(store):
    assert await store.get_room("NONE") is None


@pytest.mark.asyncio
async def test_create_room_sets_metadata_and_rejects_duplicates(store):
    assert await store.create_room("WOLF", room_state()) is True
    assert await store.create_room("WOLF", room_state()) is False

    room = await store.get_room("WOLF")
    assert room["room_id"] == "WOLF"
    assert room["version"] == 1
    assert "created_at" in room and "updated_at" in room


@pytest.mark.asyncio
async def test_update_room_applies_mutator_and_bumps_version(store):
    await store.create_room("WOLF", room_state())

    def add_vote(state):
        state["day_votes"]["p1"] = "p2"
        return state

    updated = await store.update_room("WOLF", add_vote)
    assert updated["version"] == 2
    assert updated["day_votes"] == {"p1": "p2"}
    assert (await store.get_room("WOLF"))["day_votes"] == {"p1": "p2"}


@pytest.mark.asyncio
async def test_update_missing_room_raises_value_error(store):
    with pytest.raises(ValueError):
        await store.update_room("NONE", lambda s: s)


@pytest.mark.asyncio
async def test_mutator_exception_propagates_and_leaves_state_untouched(store):
    await store.create_room("WOLF", room_state())

    class RuleViolation(Exception):
        pass

    def reject(state):
        state["phase"] = "ENDED"
        raise RuleViolation()

    with pytest.raises(RuleViolation):
        await store.update_room("WOLF", reject)
    room = await store.get_room("WOLF")
    assert room["phase"] == "DAY"
    assert room["version"] == 1


@pytest.mark.asyncio
async def test_get_room_returns_a_copy(store):
    await store.create_room("WOLF", room_state())
    room = await store.get_room("WOLF")
    room["phase"] = "HACKED"
    assert (await store.get_room("WOLF"))["phase"] == "DAY"


# ---------------------------------------------------------------------------
# 2. Concurrency (CAS): simultaneous votes must never be lost
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_votes_are_never_lost(store):
    await store.create_room("WOLF", room_state())
    voters = [f"p{i}" for i in range(1, 7)]

    def vote(player_id):
        def mutator(state):
            state["day_votes"][player_id] = "SKIP"
            return state
        return mutator

    await asyncio.gather(*(store.update_room("WOLF", vote(p)) for p in voters))

    room = await store.get_room("WOLF")
    assert set(room["day_votes"]) == set(voters)
    assert room["version"] == 1 + len(voters)


@pytest.mark.asyncio
async def test_redis_update_retries_after_concurrent_write():
    server = fakeredis.FakeServer()
    store = RedisStateStore("redis://unused:6379")
    store._redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    other_pod = fakeredis.FakeRedis(server=server, decode_responses=True)
    await store.create_room("WOLF", room_state())
    attempts = []

    def mutator(state):
        attempts.append(dict(state["day_votes"]))
        if len(attempts) == 1:
            # Another pod commits between our WATCH/GET and our EXEC
            raw = json.loads(other_pod.get("room:WOLF:state"))
            raw["day_votes"]["intruder"] = "SKIP"
            other_pod.set("room:WOLF:state", json.dumps(raw))
        state["day_votes"]["me"] = "SKIP"
        return state

    updated = await store.update_room("WOLF", mutator)
    assert len(attempts) == 2
    assert attempts[1] == {"intruder": "SKIP"}
    assert updated["day_votes"] == {"intruder": "SKIP", "me": "SKIP"}


@pytest.mark.asyncio
async def test_redis_update_raises_state_conflict_when_retries_exhausted(monkeypatch):
    import redis.asyncio.client
    from redis.exceptions import WatchError

    store = make_redis_store()
    await store.create_room("WOLF", room_state())

    async def always_conflict(self, *args, **kwargs):
        raise WatchError()

    monkeypatch.setattr(redis.asyncio.client.Pipeline, "execute", always_conflict)
    with pytest.raises(StateConflictError):
        await store.update_room("WOLF", lambda s: s, max_retries=3)


# ---------------------------------------------------------------------------
# 3. Player sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_round_trip(store):
    assert await store.get_player_session("tok_missing") is None
    await store.create_player_session("tok_abc", {"room_id": "WOLF", "player_id": "p1"})
    session = await store.get_player_session("tok_abc")
    assert session["room_id"] == "WOLF"
    assert session["player_id"] == "p1"
    assert "created_at" in session


@pytest.mark.asyncio
async def test_redis_stores_session_under_token_hash_only():
    store = make_redis_store()
    await store.create_player_session("tok_secret", {"room_id": "WOLF", "player_id": "p1"})
    r = await store._get_redis()
    keys = await r.keys("session:*")
    assert keys == [f"session:{hashlib.sha256(b'tok_secret').hexdigest()}"]
    assert 0 < await r.ttl(keys[0]) <= 86400


# ---------------------------------------------------------------------------
# 4. Chat stream
# ---------------------------------------------------------------------------

def chat_msg(text: str, channel: str = "PUBLIC") -> dict:
    return {"channel": channel, "sender_id": "p1", "sender_name": "Alice", "text": text}


@pytest.mark.asyncio
async def test_append_chat_assigns_ascending_ids(store):
    first = await store.append_chat("WOLF", chat_msg("hello"))
    second = await store.append_chat("WOLF", chat_msg("world"))
    assert (first["message_id"], second["message_id"]) == (1, 2)
    assert first["text"] == "hello"
    assert "created_at" in first


@pytest.mark.asyncio
async def test_get_chat_after_id_and_limit(store):
    for i in range(5):
        await store.append_chat("WOLF", chat_msg(f"m{i}"))
    assert [m["message_id"] for m in await store.get_chat("WOLF", after_id=2)] == [3, 4, 5]
    assert [m["message_id"] for m in await store.get_chat("WOLF", after_id=0, limit=2)] == [1, 2]
    assert await store.get_chat("EMPTY") == []


@pytest.mark.asyncio
async def test_chat_is_capped_at_history_limit(store):
    for i in range(CHAT_HISTORY_LIMIT + 5):
        await store.append_chat("WOLF", chat_msg(f"m{i}"))
    messages = await store.get_chat("WOLF", limit=CHAT_HISTORY_LIMIT + 5)
    assert len(messages) == CHAT_HISTORY_LIMIT
    assert messages[0]["message_id"] == 6
    assert messages[-1]["message_id"] == CHAT_HISTORY_LIMIT + 5


@pytest.mark.asyncio
async def test_concurrent_chat_appends_keep_list_order_equal_to_id_order(store):
    await asyncio.gather(*(store.append_chat("WOLF", chat_msg(f"m{i}")) for i in range(30)))
    ids = [m["message_id"] for m in await store.get_chat("WOLF")]
    assert ids == list(range(1, 31))


@pytest.mark.asyncio
async def test_chat_preserves_unicode_text(store):
    await store.append_chat("WOLF", chat_msg("หมาป่าคือใคร 🐺"))
    assert (await store.get_chat("WOLF"))[0]["text"] == "หมาป่าคือใคร 🐺"


# ---------------------------------------------------------------------------
# 5. Server clock (issue #9)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_server_time_returns_current_unix_seconds(store):
    now = await store.get_server_time()
    assert isinstance(now, int)
    assert abs(now - int(time.time())) <= 5
