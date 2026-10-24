import asyncio
import copy
import hashlib
import json
import random
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

ROOM_TTL_SECONDS = 86400
CHAT_HISTORY_LIMIT = 200


class StateConflictError(Exception):
    """Raised when an atomic optimistic concurrency check fails."""
    pass

class StateStore(ABC):
    @abstractmethod
    async def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def create_room(self, room_id: str, initial_state: Dict[str, Any]) -> bool:
        pass

    @abstractmethod
    async def update_room(self, room_id: str, mutator: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_player_session(self, token: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def create_player_session(self, token: str, session_data: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def append_chat(self, room_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_chat(self, room_id: str, after_id: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_server_time(self) -> int:
        """Returns authoritative Unix timestamp in seconds (Redis TIME or system clock)."""
        pass


class InMemoryStateStore(StateStore):
    """
    In-memory state store implementation for isolated development and offline unit tests.
    Does not require Redis or external infrastructure.
    """
    def __init__(self):
        self._rooms: Dict[str, Dict[str, Any]] = {}
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._chats: Dict[str, List[Dict[str, Any]]] = {}
        self._chat_seq: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            state = self._rooms.get(room_id)
            return copy.deepcopy(state) if state else None

    async def create_room(self, room_id: str, initial_state: Dict[str, Any]) -> bool:
        async with self._lock:
            if room_id in self._rooms:
                return False
            state = copy.deepcopy(initial_state)
            state.setdefault("version", 1)
            state.setdefault("created_at", int(time.time()))
            state.setdefault("updated_at", int(time.time()))
            self._rooms[room_id] = state
            self._chats[room_id] = []
            self._chat_seq[room_id] = 0
            return True

    async def update_room(self, room_id: str, mutator: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
        async with self._lock:
            if room_id not in self._rooms:
                raise ValueError(f"Room {room_id} not found")
            current_state = copy.deepcopy(self._rooms[room_id])
            updated = mutator(current_state)
            updated["version"] = updated.get("version", 0) + 1
            updated["updated_at"] = int(time.time())
            self._rooms[room_id] = copy.deepcopy(updated)
            return copy.deepcopy(updated)

    async def get_player_session(self, token: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            session = self._sessions.get(token)
            return copy.deepcopy(session) if session else None

    async def create_player_session(self, token: str, session_data: Dict[str, Any]) -> None:
        async with self._lock:
            data = copy.deepcopy(session_data)
            data.setdefault("created_at", int(time.time()))
            self._sessions[token] = data

    async def append_chat(self, room_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        async with self._lock:
            if room_id not in self._chats:
                self._chats[room_id] = []
                self._chat_seq[room_id] = 0
            self._chat_seq[room_id] += 1
            msg = copy.deepcopy(message)
            msg["message_id"] = self._chat_seq[room_id]
            msg.setdefault("created_at", int(time.time()))
            self._chats[room_id].append(msg)
            if len(self._chats[room_id]) > CHAT_HISTORY_LIMIT:
                self._chats[room_id] = self._chats[room_id][-CHAT_HISTORY_LIMIT:]
            return copy.deepcopy(msg)

    async def get_chat(self, room_id: str, after_id: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        async with self._lock:
            messages = self._chats.get(room_id, [])
            filtered = [m for m in messages if m.get("message_id", 0) > after_id]
            return copy.deepcopy(filtered[:limit])

    async def get_server_time(self) -> int:
        return int(time.time())


# Assigns the message_id and appends in one atomic step, so the list order always
# matches message_id order even when several chat pods append concurrently.
_APPEND_CHAT_LUA = """
local id = redis.call('INCR', KEYS[1])
local msg = cjson.decode(ARGV[1])
msg['message_id'] = id
local encoded = cjson.encode(msg)
redis.call('RPUSH', KEYS[2], encoded)
redis.call('LTRIM', KEYS[2], -tonumber(ARGV[2]), -1)
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('EXPIRE', KEYS[2], ARGV[3])
return encoded
"""


def _session_key(token: str) -> str:
    # Contract: session:{token_hash} -- the raw bearer token never lands in Redis.
    return f"session:{hashlib.sha256(token.encode()).hexdigest()}"


class RedisStateStore(StateStore):
    """
    Production Redis state store using redis.asyncio with CAS (WATCH/MULTI/EXEC)
    for optimistic concurrency control.
    """
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis
            # Short timeouts so a dead Redis fails fast (503) instead of hanging requests.
            self._redis = aioredis.from_url(
                self.redis_url, decode_responses=True,
                socket_connect_timeout=2, socket_timeout=2,
            )
        return self._redis

    async def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        r = await self._get_redis()
        raw = await r.get(f"room:{room_id}:state")
        return json.loads(raw) if raw else None

    async def create_room(self, room_id: str, initial_state: Dict[str, Any]) -> bool:
        r = await self._get_redis()
        key = f"room:{room_id}:state"
        state = copy.deepcopy(initial_state)
        state.setdefault("version", 1)
        state.setdefault("created_at", int(time.time()))
        state.setdefault("updated_at", int(time.time()))
        success = await r.set(key, json.dumps(state), nx=True, ex=ROOM_TTL_SECONDS)
        return bool(success)

    async def update_room(self, room_id: str, mutator: Callable[[Dict[str, Any]], Dict[str, Any]], max_retries: int = 10) -> Dict[str, Any]:
        # 10 retries: a full room (6 players) voting in the same instant must not surface 409s.
        import redis.asyncio as aioredis
        r = await self._get_redis()
        key = f"room:{room_id}:state"

        for attempt in range(max_retries):
            async with r.pipeline() as pipe:
                try:
                    await pipe.watch(key)
                    raw = await pipe.get(key)
                    if not raw:
                        raise ValueError(f"Room {room_id} not found")
                    current = json.loads(raw)
                    updated = mutator(current)
                    updated["version"] = current.get("version", 0) + 1
                    updated["updated_at"] = int(time.time())

                    pipe.multi()
                    pipe.set(key, json.dumps(updated), ex=ROOM_TTL_SECONDS)
                    await pipe.execute()
                    return updated
                except aioredis.WatchError:
                    if attempt == max_retries - 1:
                        raise StateConflictError(f"Concurrent update collision on room {room_id}")
                    # Jitter keeps colliding writers from retrying in lockstep.
                    await asyncio.sleep(random.uniform(0, 0.02 * (attempt + 1)))
        raise StateConflictError("Exceeded update retry attempts")

    async def get_player_session(self, token: str) -> Optional[Dict[str, Any]]:
        r = await self._get_redis()
        raw = await r.get(_session_key(token))
        return json.loads(raw) if raw else None

    async def create_player_session(self, token: str, session_data: Dict[str, Any]) -> None:
        r = await self._get_redis()
        data = copy.deepcopy(session_data)
        data.setdefault("created_at", int(time.time()))
        await r.set(_session_key(token), json.dumps(data), ex=ROOM_TTL_SECONDS)

    async def append_chat(self, room_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        r = await self._get_redis()
        seq_key = f"room:{room_id}:chat_seq"
        chat_key = f"room:{room_id}:chat"

        msg = copy.deepcopy(message)
        msg.setdefault("created_at", int(time.time()))
        encoded = await r.eval(
            _APPEND_CHAT_LUA, 2, seq_key, chat_key,
            json.dumps(msg), CHAT_HISTORY_LIMIT, ROOM_TTL_SECONDS,
        )
        return json.loads(encoded)

    async def get_chat(self, room_id: str, after_id: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        r = await self._get_redis()
        chat_key = f"room:{room_id}:chat"
        raw_items = await r.lrange(chat_key, 0, -1)
        messages = [json.loads(item) for item in raw_items]
        filtered = [m for m in messages if m.get("message_id", 0) > after_id]
        return filtered[:limit]

    async def get_server_time(self) -> int:
        r = await self._get_redis()
        seconds, _ = await r.time()
        return int(seconds)
