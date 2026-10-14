import pytest
from common.state_store import InMemoryStateStore
from common.trace import get_service_trace
from common.schemas import ApiResponse, TraceEntry

@pytest.mark.asyncio
async def test_in_memory_state_store_room_lifecycle():
    store = InMemoryStateStore()
    
    # 1. Create Room
    initial_state = {"room_id": "TEST", "phase": "WAITING", "players": {}}
    created = await store.create_room("TEST", initial_state)
    assert created is True
    
    # 2. Duplicate create fails
    created_dup = await store.create_room("TEST", initial_state)
    assert created_dup is False
    
    # 3. Read Room
    room = await store.get_room("TEST")
    assert room is not None
    assert room["room_id"] == "TEST"
    assert room["version"] == 1
    
    # 4. Atomic Mutation
    def add_player(state):
        state["players"]["p1"] = {"name": "Alice"}
        return state
        
    updated = await store.update_room("TEST", add_player)
    assert updated["version"] == 2
    assert "p1" in updated["players"]

@pytest.mark.asyncio
async def test_in_memory_state_store_sessions_and_chat():
    store = InMemoryStateStore()
    
    # Session
    await store.create_player_session("tok_123", {"room_id": "TEST", "player_id": "p1"})
    session = await store.get_player_session("tok_123")
    assert session is not None
    assert session["player_id"] == "p1"
    
    # Chat
    msg1 = await store.append_chat("TEST", {"channel": "PUBLIC", "text": "hello"})
    assert msg1["message_id"] == 1
    
    msg2 = await store.append_chat("TEST", {"channel": "PUBLIC", "text": "world"})
    assert msg2["message_id"] == 2
    
    history = await store.get_chat("TEST", after_id=0)
    assert len(history) == 2
    assert history[0]["text"] == "hello"

def test_downward_api_trace_default():
    trace = get_service_trace("test-svc")
    assert trace["service"] == "test-svc"
    assert "local" in trace["pod"]
    assert "local" in trace["node"]

def test_api_response_schema():
    resp = ApiResponse(
        ok=True,
        data={"room_id": "TEST"},
        request_id="req-123",
        trace=[TraceEntry(service="gateway", pod="p1", node="n1")]
    )
    dumped = resp.model_dump()
    assert dumped["ok"] is True
    assert dumped["request_id"] == "req-123"
    assert len(dumped["trace"]) == 1
