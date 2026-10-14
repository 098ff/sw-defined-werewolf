import asyncio
import copy
import json
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

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
            # Cap at 200 messages
            if len(self._chats[room_id]) > 200:
                self._chats[room_id] = self._chats[room_id][-200:]
            return copy.deepcopy(msg)

    async def get_chat(self, room_id: str, after_id: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        async with self._lock:
            messages = self._chats.get(room_id, [])
            filtered = [m for m in messages if m.get("message_id", 0) > after_id]
            return copy.deepcopy(filtered[:limit])


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
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
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
        success = await r.set(key, json.dumps(state), nx=True, ex=86400)
        return bool(success)

    async def update_room(self, room_id: str, mutator: Callable[[Dict[str, Any]], Dict[str, Any]], max_retries: int = 3) -> Dict[str, Any]:
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
                    pipe.set(key, json.dumps(updated), ex=86400)
                    await pipe.execute()
                    return updated
                except aioredis.WatchError:
                    if attempt == max_retries - 1:
                        raise StateConflictError(f"Concurrent update collision on room {room_id}")
                    await asyncio.sleep(0.05 * (attempt + 1))
        raise StateConflictError("Exceeded update retry attempts")

    async def get_player_session(self, token: str) -> Optional[Dict[str, Any]]:
        r = await self._get_redis()
        raw = await r.get(f"session:{token}")
        return json.loads(raw) if raw else None

    async def create_player_session(self, token: str, session_data: Dict[str, Any]) -> None:
        r = await self._get_redis()
        data = copy.deepcopy(session_data)
        data.setdefault("created_at", int(time.time()))
        await r.set(f"session:{token}", json.dumps(data), ex=86400)

    async def append_chat(self, room_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        r = await self._get_redis()
        seq_key = f"room:{room_id}:chat_seq"
        chat_key = f"room:{room_id}:chat"

        msg_id = await r.incr(seq_key)
        msg = copy.deepcopy(message)
        msg["message_id"] = msg_id
        msg.setdefault("created_at", int(time.time()))

        async with r.pipeline() as pipe:
            pipe.rpush(chat_key, json.dumps(msg))
            pipe.ltrim(chat_key, -200, -1)
            pipe.expire(chat_key, 86400)
            pipe.expire(seq_key, 86400)
            await pipe.execute()

        return msg

    async def get_chat(self, room_id: str, after_id: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        r = await self._get_redis()
        chat_key = f"room:{room_id}:chat"
        raw_items = await r.lrange(chat_key, 0, -1)
        messages = [json.loads(item) for item in raw_items]
        filtered = [m for m in messages if m.get("message_id", 0) > after_id]
        return filtered[:limit]
