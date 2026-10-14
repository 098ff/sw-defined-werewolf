from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class TraceEntry(BaseModel):
    service: str
    pod: str
    node: str

class ErrorDetail(BaseModel):
    code: str
    message: str

class ApiResponse(BaseModel):
    ok: bool = True
    data: Optional[Any] = None
    error: Optional[ErrorDetail] = None
    request_id: str
    trace: List[TraceEntry] = Field(default_factory=list)

class PlayerInfo(BaseModel):
    player_id: str
    name: str
    role: Optional[str] = None
    alive: bool = True
    is_host: bool = False

class PlayerView(BaseModel):
    room_id: str
    phase: str
    day_count: int
    phase_version: int
    phase_end_time: int
    winner: Optional[str] = None
    announcement: str
    me: PlayerInfo
    players: List[PlayerInfo]
