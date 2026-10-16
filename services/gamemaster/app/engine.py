"""
Pure Werewolf rule engine.

Every function here operates on plain dicts (the InternalRoomState schema from
contracts/api-contract.md) and takes the current server time as an argument.
No HTTP, no Redis, no wall clock -- so all rules are unit-testable with pytest
and the FastAPI layer can run them inside StateStore.update_room() mutators.
"""
import random
from typing import Any, Dict, List, Optional, Tuple

NIGHT_DURATION_SECONDS = 45
DAY_DURATION_SECONDS = 60

ROLE_CONFIGS = {
    4: ["WEREWOLF", "DOCTOR", "SEER", "VILLAGER"],
    5: ["WEREWOLF", "DOCTOR", "SEER", "VILLAGER", "VILLAGER"],
    6: ["WEREWOLF", "WEREWOLF", "DOCTOR", "SEER", "VILLAGER", "VILLAGER"],
}

GOOD_ROLES = {"DOCTOR", "SEER", "VILLAGER"}

# Night action name expected from each role in POST /night-actions
ACTION_BY_ROLE = {
    "WEREWOLF": "WEREWOLF_KILL",
    "DOCTOR": "DOCTOR_PROTECT",
    "SEER": "SEER_CHECK",
}

SKIP = "SKIP"


class GameError(Exception):
    """Rule violation that maps directly onto the standard error envelope."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def empty_night_actions(seer_results: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Seer results survive across nights so the Seer can use them during the day
    return {
        "wolf_votes": {},
        "doctor_target": None,
        "seer_target": None,
        "seer_result_by_player": dict(seer_results or {}),
    }


def _name(players: Dict[str, Dict[str, Any]], player_id: str) -> str:
    return players[player_id].get("name", player_id)


def _alive(players: Dict[str, Dict[str, Any]], player_id: Optional[str]) -> bool:
    return player_id in players and players[player_id].get("alive", True)


# ---------------------------------------------------------------------------
# Role assignment & win condition
# ---------------------------------------------------------------------------

def assign_roles(player_ids: List[str], rng: random.Random = None) -> Dict[str, str]:
    count = len(player_ids)
    if count not in ROLE_CONFIGS:
        raise GameError(400, "INVALID_REQUEST", f"Requires 4-6 players, got {count}")
    roles = ROLE_CONFIGS[count].copy()
    (rng or random).shuffle(roles)
    return dict(zip(player_ids, roles))


def check_win_condition(players: Dict[str, Dict[str, Any]]) -> Optional[str]:
    alive_wolves = sum(1 for p in players.values() if p.get("alive", True) and p.get("role") == "WEREWOLF")
    alive_good = sum(1 for p in players.values() if p.get("alive", True) and p.get("role") in GOOD_ROLES)
    if alive_wolves == 0:
        return "VILLAGER"
    if alive_wolves >= alive_good:
        return "WEREWOLF"
    return None


# ---------------------------------------------------------------------------
# Resolution algorithms
# ---------------------------------------------------------------------------

def tally_wolf_votes(players: Dict[str, Dict[str, Any]], wolf_votes: Dict[str, str]) -> Optional[str]:
    """Target holding a strict majority of the living werewolves' cast votes, else None."""
    counts: Dict[str, int] = {}
    for wolf_id, target_id in wolf_votes.items():
        if _alive(players, wolf_id) and players[wolf_id].get("role") == "WEREWOLF" and _alive(players, target_id):
            counts[target_id] = counts.get(target_id, 0) + 1
    total = sum(counts.values())
    for target_id, n in counts.items():
        if n * 2 > total:
            return target_id
    return None


def resolve_night(players: Dict[str, Dict[str, Any]], night_actions: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """
    Applies the night pipeline in place. Returns (casualty_id or None, announcement).
    Records the Seer result into night_actions["seer_result_by_player"].
    """
    victim = tally_wolf_votes(players, night_actions.get("wolf_votes", {}))
    if victim is not None and night_actions.get("doctor_target") == victim:
        victim = None
    if victim is not None:
        players[victim]["alive"] = False

    seer_target = night_actions.get("seer_target")
    if seer_target in players:
        seer_id = next((pid for pid, p in players.items() if p.get("role") == "SEER"), None)
        if seer_id is not None:
            alignment = "WEREWOLF" if players[seer_target].get("role") == "WEREWOLF" else "GOOD"
            night_actions.setdefault("seer_result_by_player", {})[seer_id] = {
                "target_id": seer_target,
                "result": alignment,
            }

    if victim is None:
        return None, "Dawn breaks. Nobody died during the night."
    return victim, f"Dawn breaks. {_name(players, victim)} was killed during the night."


def resolve_day(players: Dict[str, Dict[str, Any]], day_votes: Dict[str, str]) -> Tuple[Optional[str], str]:
    """Applies the day vote algorithm in place. Returns (executed_id or None, announcement)."""
    skip_votes = 0
    counts: Dict[str, int] = {}
    for voter_id, target_id in day_votes.items():
        if not _alive(players, voter_id):
            continue
        if target_id == SKIP:
            skip_votes += 1
        elif _alive(players, target_id):
            counts[target_id] = counts.get(target_id, 0) + 1

    if skip_votes + sum(counts.values()) == 0:
        return None, "Nobody voted. No one was executed today."
    if not counts:
        return None, "The village chose to skip. No one was executed today."

    highest = max(counts.values())
    leaders = [pid for pid, n in counts.items() if n == highest]
    if skip_votes >= highest:
        return None, "The village chose to skip. No one was executed today."
    if len(leaders) > 1:
        return None, "The vote was tied. No one was executed today."

    executed = leaders[0]
    players[executed]["alive"] = False
    return executed, f"The village executed {_name(players, executed)}."


def all_night_actions_submitted(players: Dict[str, Dict[str, Any]], night_actions: Dict[str, Any]) -> bool:
    for pid, p in players.items():
        if not p.get("alive", True):
            continue
        role = p.get("role")
        if role == "WEREWOLF" and pid not in night_actions.get("wolf_votes", {}):
            return False
        if role == "DOCTOR" and night_actions.get("doctor_target") is None:
            return False
        if role == "SEER" and night_actions.get("seer_target") is None:
            return False
    return True


# ---------------------------------------------------------------------------
# Phase state machine
# ---------------------------------------------------------------------------

def _enter_phase(state: Dict[str, Any], phase: str, now: int, duration: int) -> None:
    state["phase"] = phase
    state["phase_version"] = state.get("phase_version", 0) + 1
    state["phase_end_time"] = now + duration


def _end_game(state: Dict[str, Any], winner: str, announcement: str) -> None:
    state["phase"] = "ENDED"
    state["phase_version"] = state.get("phase_version", 0) + 1
    state["phase_end_time"] = 0
    state["winner"] = winner
    team = "Villagers" if winner == "VILLAGER" else "Werewolves"
    state["announcement"] = f"{announcement} {team} win!"


def initialize_game(state: Dict[str, Any], now: int, rng: random.Random = None) -> Dict[str, Any]:
    """WAITING -> NIGHT: assigns roles and starts Night 1."""
    if state.get("phase", "WAITING") != "WAITING":
        raise GameError(409, "GAME_ALREADY_STARTED", "Game has already started")
    players = state.get("players", {})
    roles = assign_roles(list(players.keys()), rng)
    for pid, role in roles.items():
        players[pid]["role"] = role
        players[pid]["alive"] = True

    state["day_count"] = 1
    state["winner"] = None
    state["night_actions"] = empty_night_actions()
    state["day_votes"] = {}
    _enter_phase(state, "NIGHT", now, NIGHT_DURATION_SECONDS)
    state["announcement"] = "Night 1 has fallen over the village. Villagers sleep."
    return state


def advance_phase(state: Dict[str, Any], now: int) -> Dict[str, Any]:
    """Resolves the current phase and moves to the next one (NIGHT->DAY/ENDED, DAY->NIGHT/ENDED)."""
    players = state["players"]
    phase = state.get("phase")

    if phase == "NIGHT":
        night_actions = state.get("night_actions") or empty_night_actions()
        _, announcement = resolve_night(players, night_actions)
        winner = check_win_condition(players)
        if winner:
            state["night_actions"] = night_actions
            _end_game(state, winner, announcement)
            return state
        state["night_actions"] = empty_night_actions(night_actions.get("seer_result_by_player"))
        state["day_votes"] = {}
        _enter_phase(state, "DAY", now, DAY_DURATION_SECONDS)
        state["announcement"] = f"{announcement} Day {state.get('day_count', 1)} begins: discuss and vote."
        return state

    if phase == "DAY":
        _, announcement = resolve_day(players, state.get("day_votes", {}))
        winner = check_win_condition(players)
        if winner:
            _end_game(state, winner, announcement)
            return state
        state["day_count"] = state.get("day_count", 1) + 1
        state["day_votes"] = {}
        _enter_phase(state, "NIGHT", now, NIGHT_DURATION_SECONDS)
        state["announcement"] = f"{announcement} Night {state['day_count']} has fallen."
        return state

    raise GameError(400, "INVALID_REQUEST", f"Cannot advance from phase {phase}")


def is_expired(state: Dict[str, Any], now: int) -> bool:
    return state.get("phase") in ("NIGHT", "DAY") and now >= state.get("phase_end_time", 0)


def advance_if_expired(state: Dict[str, Any], now: int) -> bool:
    """Advances one phase if the server-clock timer has run out. Returns True if state changed."""
    if is_expired(state, now):
        advance_phase(state, now)
        return True
    return False


# ---------------------------------------------------------------------------
# Player actions
# ---------------------------------------------------------------------------

def _check_actor(state: Dict[str, Any], player_id: str, phase: str, phase_version: int) -> Dict[str, Any]:
    if state.get("phase_version") != phase_version:
        raise GameError(409, "PHASE_VERSION_CONFLICT", "Phase has changed; refresh and try again")
    if state.get("phase") != phase:
        raise GameError(400, "INVALID_REQUEST", f"Action only allowed during {phase}")
    player = state["players"].get(player_id)
    if player is None or not player.get("alive", True):
        raise GameError(403, "FORBIDDEN_ROLE", "Dead players cannot act")
    return player


def _record_once(container: Dict[str, Any], key: str, target_id: str) -> None:
    existing = container.get(key)
    if existing is not None and existing != target_id:
        raise GameError(409, "ACTION_ALREADY_SUBMITTED", "You already submitted a different choice this phase")
    container[key] = target_id


def submit_night_action(state: Dict[str, Any], player_id: str, action: str, target_id: str,
                        phase_version: int, now: int) -> Dict[str, Any]:
    """Validates and records a night action; resolves the night early once everyone has acted."""
    players = state["players"]
    player = _check_actor(state, player_id, "NIGHT", phase_version)
    role = player.get("role")
    if ACTION_BY_ROLE.get(role) != action:
        raise GameError(403, "FORBIDDEN_ROLE", f"Role {role} cannot perform {action}")
    if not _alive(players, target_id):
        raise GameError(400, "INVALID_REQUEST", "Target must be a living player")
    if role in ("WEREWOLF", "SEER") and target_id == player_id:
        raise GameError(400, "INVALID_REQUEST", "You cannot target yourself")

    night_actions = state.setdefault("night_actions", empty_night_actions())
    if role == "WEREWOLF":
        _record_once(night_actions.setdefault("wolf_votes", {}), player_id, target_id)
    elif role == "DOCTOR":
        _record_once(night_actions, "doctor_target", target_id)
    else:
        _record_once(night_actions, "seer_target", target_id)

    if all_night_actions_submitted(players, night_actions):
        advance_phase(state, now)
    return state


def submit_vote(state: Dict[str, Any], player_id: str, target_id: str, phase_version: int) -> Dict[str, Any]:
    _check_actor(state, player_id, "DAY", phase_version)
    if target_id != SKIP and not _alive(state["players"], target_id):
        raise GameError(400, "INVALID_REQUEST", "Vote target must be a living player or SKIP")
    _record_once(state.setdefault("day_votes", {}), player_id, target_id)
    return state


# ---------------------------------------------------------------------------
# PlayerView sanitizer (security invariant: never leak other players' roles)
# ---------------------------------------------------------------------------

def build_player_view(state: Dict[str, Any], caller_id: str, now: int) -> Dict[str, Any]:
    players = state.get("players", {})
    me = players.get(caller_id, {})
    my_role = me.get("role")
    game_ended = state.get("phase") == "ENDED"

    sanitized = []
    for pid, p in players.items():
        visible = (
            pid == caller_id
            or game_ended
            or (my_role == "WEREWOLF" and p.get("role") == "WEREWOLF")
        )
        sanitized.append({
            "player_id": pid,
            "name": p.get("name", pid),
            "alive": p.get("alive", True),
            "role": p.get("role") if visible else None,
            "is_host": p.get("is_host", False),
        })

    private_info: Dict[str, Any] = {}
    if my_role == "SEER":
        result = (state.get("night_actions") or {}).get("seer_result_by_player", {}).get(caller_id)
        if result:
            private_info["seer_result"] = result

    return {
        "room_id": state.get("room_id"),
        "phase": state.get("phase"),
        "day_count": state.get("day_count", 1),
        "phase_version": state.get("phase_version", 0),
        "phase_end_time": state.get("phase_end_time", 0),
        "server_time": now,
        "winner": state.get("winner"),
        "announcement": state.get("announcement", ""),
        "me": {
            "player_id": caller_id,
            "name": me.get("name", "Unknown"),
            "role": my_role,
            "alive": me.get("alive", True),
            "is_host": me.get("is_host", False),
            "private_info": private_info,
        },
        "players": sanitized,
    }
