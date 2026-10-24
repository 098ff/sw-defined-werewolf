"""
Unit tests for GameMaster Rule Engine and FastAPI Service.

Follows specifications from:
  - docs/roles/04-role-gamemaster.md
  - docs/02-game-rules-and-ux.md
  - contracts/api-contract.md
"""
import sys
from pathlib import Path
from typing import Any, Dict

import pytest
from httpx import ASGITransport, AsyncClient

# Ensure repo root and gamemaster service are on sys.path
ROOT = Path(__file__).resolve().parents[2]
GM_DIR = ROOT / "services" / "gamemaster"
for p in [str(ROOT), str(GM_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app import engine
from app.engine import (
    DAY_DURATION_SECONDS,
    NIGHT_DURATION_SECONDS,
    ROLE_CONFIGS,
    GameError,
    _alive,
    advance_if_expired,
    advance_phase,
    all_night_actions_submitted,
    assign_roles,
    build_player_view,
    check_win_condition,
    empty_night_actions,
    initialize_game,
    is_expired,
    resolve_day,
    resolve_night,
    submit_night_action,
    submit_vote,
    tally_wolf_votes,
)
from app.main import app, store
from common.state_store import InMemoryStateStore


# ===========================================================================
# 1. Role Assignment Algorithm Tests
# ===========================================================================

def test_assign_roles_4_players():
    pids = ["p1", "p2", "p3", "p4"]
    roles = assign_roles(pids)
    assert len(roles) == 4
    role_counts = {r: list(roles.values()).count(r) for r in ROLE_CONFIGS[4]}
    assert role_counts["WEREWOLF"] == 1
    assert role_counts["DOCTOR"] == 1
    assert role_counts["SEER"] == 1
    assert role_counts["VILLAGER"] == 1


def test_assign_roles_5_players():
    pids = ["p1", "p2", "p3", "p4", "p5"]
    roles = assign_roles(pids)
    assert len(roles) == 5
    role_counts = {r: list(roles.values()).count(r) for r in set(ROLE_CONFIGS[5])}
    assert role_counts["WEREWOLF"] == 1
    assert role_counts["DOCTOR"] == 1
    assert role_counts["SEER"] == 1
    assert role_counts["VILLAGER"] == 2


def test_assign_roles_6_players():
    pids = ["p1", "p2", "p3", "p4", "p5", "p6"]
    roles = assign_roles(pids)
    assert len(roles) == 6
    role_counts = {r: list(roles.values()).count(r) for r in set(ROLE_CONFIGS[6])}
    assert role_counts["WEREWOLF"] == 2
    assert role_counts["DOCTOR"] == 1
    assert role_counts["SEER"] == 1
    assert role_counts["VILLAGER"] == 2


@pytest.mark.parametrize("invalid_count", [0, 1, 2, 3, 7, 8])
def test_assign_roles_invalid_player_count(invalid_count):
    pids = [f"p{i}" for i in range(invalid_count)]
    with pytest.raises(GameError) as exc_info:
        assign_roles(pids)
    assert exc_info.value.status == 400
    assert exc_info.value.code == "INVALID_REQUEST"


# ===========================================================================
# 2. Win Condition Tests
# ===========================================================================

def test_win_condition_villagers_win_when_all_wolves_dead():
    players = {
        "p1": {"role": "WEREWOLF", "alive": False},
        "p2": {"role": "DOCTOR", "alive": True},
        "p3": {"role": "SEER", "alive": True},
        "p4": {"role": "VILLAGER", "alive": True},
    }
    assert check_win_condition(players) == "VILLAGER"


def test_win_condition_wolves_win_when_equal_to_good():
    # 1 wolf == 1 good (doctor)
    players = {
        "p1": {"role": "WEREWOLF", "alive": True},
        "p2": {"role": "DOCTOR", "alive": True},
        "p3": {"role": "VILLAGER", "alive": False},
    }
    assert check_win_condition(players) == "WEREWOLF"


def test_win_condition_wolves_win_when_outnumber_good():
    # 2 wolves > 1 villager
    players = {
        "p1": {"role": "WEREWOLF", "alive": True},
        "p2": {"role": "WEREWOLF", "alive": True},
        "p3": {"role": "VILLAGER", "alive": True},
    }
    assert check_win_condition(players) == "WEREWOLF"


def test_win_condition_game_continues():
    # 1 wolf < 3 good -> None
    players = {
        "p1": {"role": "WEREWOLF", "alive": True},
        "p2": {"role": "DOCTOR", "alive": True},
        "p3": {"role": "SEER", "alive": True},
        "p4": {"role": "VILLAGER", "alive": True},
    }
    assert check_win_condition(players) is None


# ===========================================================================
# 3. Werewolf Tally & Night Resolution Tests
# ===========================================================================

def test_werewolf_tally_strict_majority():
    players = {
        "w1": {"role": "WEREWOLF", "alive": True},
        "w2": {"role": "WEREWOLF", "alive": True},
        "v1": {"role": "VILLAGER", "alive": True},
        "v2": {"role": "VILLAGER", "alive": True},
    }
    # Both wolves agree on v1
    wolf_votes = {"w1": "v1", "w2": "v1"}
    assert tally_wolf_votes(players, wolf_votes) == "v1"


def test_werewolf_tally_tie_results_in_no_target():
    players = {
        "w1": {"role": "WEREWOLF", "alive": True},
        "w2": {"role": "WEREWOLF", "alive": True},
        "v1": {"role": "VILLAGER", "alive": True},
        "v2": {"role": "VILLAGER", "alive": True},
    }
    # Split vote
    wolf_votes = {"w1": "v1", "w2": "v2"}
    assert tally_wolf_votes(players, wolf_votes) is None


def test_werewolf_tally_ignores_dead_wolf_or_dead_target():
    players = {
        "w1": {"role": "WEREWOLF", "alive": True},
        "w2": {"role": "WEREWOLF", "alive": False},  # dead wolf
        "v1": {"role": "VILLAGER", "alive": False},  # dead target
        "v2": {"role": "VILLAGER", "alive": True},
    }
    # w2 is dead, so only w1's vote counts
    wolf_votes = {"w1": "v2", "w2": "v1"}
    assert tally_wolf_votes(players, wolf_votes) == "v2"


def test_resolve_night_doctor_saves_victim():
    players = {
        "w1": {"role": "WEREWOLF", "alive": True, "name": "Wolf"},
        "doc": {"role": "DOCTOR", "alive": True, "name": "Doc"},
        "v1": {"role": "VILLAGER", "alive": True, "name": "Villager"},
    }
    night_actions = {
        "wolf_votes": {"w1": "v1"},
        "doctor_target": "v1",  # Saved!
        "seer_target": None,
        "seer_result_by_player": {},
    }
    victim, announcement = resolve_night(players, night_actions)
    assert victim is None
    assert players["v1"]["alive"] is True
    assert "Nobody died" in announcement


def test_resolve_night_casualty_applied_when_not_saved():
    players = {
        "w1": {"role": "WEREWOLF", "alive": True, "name": "Wolf"},
        "doc": {"role": "DOCTOR", "alive": True, "name": "Doc"},
        "v1": {"role": "VILLAGER", "alive": True, "name": "Villager"},
    }
    night_actions = {
        "wolf_votes": {"w1": "v1"},
        "doctor_target": "doc",  # Doc protected self, v1 left unprotected
        "seer_target": None,
        "seer_result_by_player": {},
    }
    victim, announcement = resolve_night(players, night_actions)
    assert victim == "v1"
    assert players["v1"]["alive"] is False
    assert "Villager was killed" in announcement


def test_resolve_night_seer_inspection_recorded():
    players = {
        "w1": {"role": "WEREWOLF", "alive": True, "name": "Wolf"},
        "seer": {"role": "SEER", "alive": True, "name": "Seer"},
        "v1": {"role": "VILLAGER", "alive": True, "name": "Villager"},
    }
    night_actions = {
        "wolf_votes": {"w1": "v1"},
        "doctor_target": None,
        "seer_target": "w1",  # Inspecting wolf
        "seer_result_by_player": {},
    }
    resolve_night(players, night_actions)
    seer_res = night_actions["seer_result_by_player"].get("seer")
    assert seer_res is not None
    assert seer_res["target_id"] == "w1"
    assert seer_res["result"] == "WEREWOLF"


def test_resolve_night_seer_inspects_good_player():
    players = {
        "w1": {"role": "WEREWOLF", "alive": True, "name": "Wolf"},
        "seer": {"role": "SEER", "alive": True, "name": "Seer"},
        "v1": {"role": "VILLAGER", "alive": True, "name": "Villager"},
    }
    night_actions = {
        "wolf_votes": {"w1": "v1"},
        "doctor_target": None,
        "seer_target": "v1",  # Inspecting villager
        "seer_result_by_player": {},
    }
    resolve_night(players, night_actions)
    seer_res = night_actions["seer_result_by_player"].get("seer")
    assert seer_res is not None
    assert seer_res["result"] == "GOOD"


# ===========================================================================
# 4. Day Voting Pipeline Tests
# ===========================================================================

def test_resolve_day_majority_execution():
    players = {
        "p1": {"name": "Alice", "alive": True},
        "p2": {"name": "Bob", "alive": True},
        "p3": {"name": "Carol", "alive": True},
        "p4": {"name": "Dave", "alive": True},
    }
    # Alice gets 3 votes, Bob gets 1 vote
    day_votes = {"p2": "p1", "p3": "p1", "p4": "p1", "p1": "p2"}
    executed, announcement = resolve_day(players, day_votes)
    assert executed == "p1"
    assert players["p1"]["alive"] is False
    assert "The village executed Alice" in announcement


def test_resolve_day_skip_votes_majority_or_tie():
    players = {
        "p1": {"name": "Alice", "alive": True},
        "p2": {"name": "Bob", "alive": True},
        "p3": {"name": "Carol", "alive": True},
    }
    # 2 SKIP votes, 1 vote for Alice
    day_votes = {"p1": "SKIP", "p2": "SKIP", "p3": "p1"}
    executed, announcement = resolve_day(players, day_votes)
    assert executed is None
    assert "chose to skip" in announcement

    # SKIP ties with highest candidate (1 SKIP vs 1 Alice)
    day_votes_tie_skip = {"p1": "SKIP", "p2": "p3"}
    executed, announcement = resolve_day(players, day_votes_tie_skip)
    assert executed is None
    assert "chose to skip" in announcement


def test_resolve_day_tie_between_candidates_no_execution():
    players = {
        "p1": {"name": "Alice", "alive": True},
        "p2": {"name": "Bob", "alive": True},
        "p3": {"name": "Carol", "alive": True},
        "p4": {"name": "Dave", "alive": True},
    }
    # Tie: 2 votes for Alice, 2 votes for Bob
    day_votes = {"p1": "p2", "p3": "p2", "p2": "p1", "p4": "p1"}
    executed, announcement = resolve_day(players, day_votes)
    assert executed is None
    assert "tied" in announcement


def test_resolve_day_no_ballots_cast():
    players = {"p1": {"name": "Alice", "alive": True}}
    executed, announcement = resolve_day(players, {})
    assert executed is None
    assert "Nobody voted" in announcement


# ===========================================================================
# 5. All Night Actions Submitted Check
# ===========================================================================

def test_all_night_actions_submitted_all_living_acted():
    players = {
        "w1": {"role": "WEREWOLF", "alive": True},
        "doc": {"role": "DOCTOR", "alive": True},
        "seer": {"role": "SEER", "alive": True},
        "v1": {"role": "VILLAGER", "alive": True},
    }
    night_actions = {
        "wolf_votes": {"w1": "v1"},
        "doctor_target": "w1",
        "seer_target": "doc",
    }
    assert all_night_actions_submitted(players, night_actions) is True


def test_all_night_actions_submitted_missing_active_role():
    players = {
        "w1": {"role": "WEREWOLF", "alive": True},
        "doc": {"role": "DOCTOR", "alive": True},
        "seer": {"role": "SEER", "alive": True},
    }
    night_actions = {
        "wolf_votes": {"w1": "doc"},
        "doctor_target": "w1",
        "seer_target": None,  # Seer hasn't acted
    }
    assert all_night_actions_submitted(players, night_actions) is False


def test_all_night_actions_submitted_skips_dead_roles():
    players = {
        "w1": {"role": "WEREWOLF", "alive": True},
        "doc": {"role": "DOCTOR", "alive": False},  # Dead Doctor
        "seer": {"role": "SEER", "alive": True},
    }
    night_actions = {
        "wolf_votes": {"w1": "seer"},
        "doctor_target": None,  # Dead doctor does not need to submit
        "seer_target": "w1",
    }
    assert all_night_actions_submitted(players, night_actions) is True


# ===========================================================================
# 6. FSM Phase Transitions & Clock Expiry Tests
# ===========================================================================

def test_initialize_game_transitions_waiting_to_night():
    now = 1000
    state = {
        "room_id": "TEST",
        "phase": "WAITING",
        "players": {
            "p1": {"name": "Alice"},
            "p2": {"name": "Bob"},
            "p3": {"name": "Carol"},
            "p4": {"name": "Dave"},
        },
    }
    new_state = initialize_game(state, now)
    assert new_state["phase"] == "NIGHT"
    assert new_state["day_count"] == 1
    assert new_state["phase_version"] == 1
    assert new_state["phase_end_time"] == now + NIGHT_DURATION_SECONDS
    assert new_state["winner"] is None


def test_initialize_game_fails_if_already_started():
    state = {"phase": "NIGHT", "players": {}}
    with pytest.raises(GameError) as exc_info:
        initialize_game(state, 1000)
    assert exc_info.value.status == 409
    assert exc_info.value.code == "GAME_ALREADY_STARTED"


def test_advance_phase_night_to_day_and_day_to_night():
    now = 1000
    players = {
        "w1": {"name": "Wolf", "role": "WEREWOLF", "alive": True},
        "doc": {"name": "Doc", "role": "DOCTOR", "alive": True},
        "v1": {"name": "Villager 1", "role": "VILLAGER", "alive": True},
        "v2": {"name": "Villager 2", "role": "VILLAGER", "alive": True},
    }
    state = {
        "room_id": "TEST",
        "phase": "NIGHT",
        "day_count": 1,
        "phase_version": 1,
        "players": players,
        "night_actions": {"wolf_votes": {"w1": "v1"}, "doctor_target": "v1"},
    }

    # 1. Advance NIGHT -> DAY
    day_state = advance_phase(state, now)
    assert day_state["phase"] == "DAY"
    assert day_state["day_count"] == 1
    assert day_state["phase_end_time"] == now + DAY_DURATION_SECONDS
    assert day_state["phase_version"] == 2

    # 2. Advance DAY -> NIGHT
    # Say the village skips execution
    day_state["day_votes"] = {"w1": "SKIP", "doc": "SKIP"}
    night_state = advance_phase(day_state, now + 60)
    assert night_state["phase"] == "NIGHT"
    assert night_state["day_count"] == 2
    assert night_state["phase_end_time"] == now + 60 + NIGHT_DURATION_SECONDS
    assert night_state["phase_version"] == 3


def test_advance_if_expired_evaluates_server_clock():
    now = 1000
    state = {
        "phase": "NIGHT",
        "phase_end_time": now + 45,
        "players": {
            "w1": {"role": "WEREWOLF", "alive": True},
            "v1": {"role": "VILLAGER", "alive": True},
            "v2": {"role": "VILLAGER", "alive": True},
            "v3": {"role": "VILLAGER", "alive": True},
        },
    }
    # Before timeout: should NOT advance
    assert is_expired(state, now + 44) is False
    assert advance_if_expired(state, now + 44) is False
    assert state["phase"] == "NIGHT"

    # Exactly at or after timeout: SHOULD advance
    assert is_expired(state, now + 45) is True
    assert advance_if_expired(state, now + 45) is True
    assert state["phase"] == "DAY"


# ===========================================================================
# 7. Player Actions & Validation Invariants
# ===========================================================================

def test_submit_night_action_villager_rejected():
    state = {
        "phase": "NIGHT",
        "phase_version": 1,
        "players": {
            "v1": {"role": "VILLAGER", "alive": True},
            "w1": {"role": "WEREWOLF", "alive": True},
        },
    }
    with pytest.raises(GameError) as exc:
        submit_night_action(state, "v1", "WEREWOLF_KILL", "w1", 1, 1000)
    assert exc.value.status == 403
    assert exc.value.code == "FORBIDDEN_ROLE"


def test_submit_night_action_dead_player_rejected():
    state = {
        "phase": "NIGHT",
        "phase_version": 1,
        "players": {
            "w1": {"role": "WEREWOLF", "alive": False},
            "v1": {"role": "VILLAGER", "alive": True},
        },
    }
    with pytest.raises(GameError) as exc:
        submit_night_action(state, "w1", "WEREWOLF_KILL", "v1", 1, 1000)
    assert exc.value.status == 403
    assert exc.value.code == "FORBIDDEN_ROLE"


def test_submit_night_action_werewolf_targeting_self_rejected():
    state = {
        "phase": "NIGHT",
        "phase_version": 1,
        "players": {"w1": {"role": "WEREWOLF", "alive": True}},
    }
    with pytest.raises(GameError) as exc:
        submit_night_action(state, "w1", "WEREWOLF_KILL", "w1", 1, 1000)
    assert exc.value.status == 400
    assert exc.value.code == "INVALID_REQUEST"


def test_submit_night_action_idempotent_vs_conflicting():
    state = {
        "phase": "NIGHT",
        "phase_version": 1,
        "players": {
            "w1": {"role": "WEREWOLF", "alive": True},
            "doc": {"role": "DOCTOR", "alive": True},
            "v1": {"role": "VILLAGER", "alive": True},
            "v2": {"role": "VILLAGER", "alive": True},
        },
        "night_actions": empty_night_actions(),
    }
    # 1. First submission (doc hasn't acted yet, so night stays active): succeeds
    submit_night_action(state, "w1", "WEREWOLF_KILL", "v1", 1, 1000)
    assert state["night_actions"]["wolf_votes"]["w1"] == "v1"

    # 2. Idempotent re-submission (same target): succeeds
    submit_night_action(state, "w1", "WEREWOLF_KILL", "v1", 1, 1000)
    assert state["night_actions"]["wolf_votes"]["w1"] == "v1"

    # 3. Conflicting submission (different target): rejected with 409
    with pytest.raises(GameError) as exc:
        submit_night_action(state, "w1", "WEREWOLF_KILL", "v2", 1, 1000)
    assert exc.value.status == 409
    assert exc.value.code == "ACTION_ALREADY_SUBMITTED"


def test_submit_vote_stale_phase_version_rejected():
    state = {
        "phase": "DAY",
        "phase_version": 2,
        "players": {"p1": {"alive": True}, "p2": {"alive": True}},
    }
    with pytest.raises(GameError) as exc:
        submit_vote(state, "p1", "p2", phase_version=1, now=1000)  # stale version
    assert exc.value.status == 409
    assert exc.value.code == "PHASE_VERSION_CONFLICT"


def _day_state(roles: Dict[str, str]) -> Dict[str, Any]:
    return {
        "phase": "DAY",
        "phase_version": 2,
        "day_count": 1,
        "phase_end_time": 1060,
        "players": {pid: {"name": pid, "role": role, "alive": True} for pid, role in roles.items()},
        "night_actions": empty_night_actions(),
        "day_votes": {},
    }


FIVE_ROLES = {"w1": "WEREWOLF", "seer": "SEER", "doc": "DOCTOR", "v1": "VILLAGER", "v2": "VILLAGER"}


def test_all_day_votes_submitted_ignores_dead_players():
    players = {pid: {"role": role, "alive": True} for pid, role in FIVE_ROLES.items()}
    players["v2"]["alive"] = False
    votes = {"w1": "SKIP", "seer": "w1", "doc": "w1"}
    assert engine.all_day_votes_submitted(players, votes) is False
    votes["v1"] = "w1"
    assert engine.all_day_votes_submitted(players, votes) is True


def test_day_stays_open_until_every_living_player_votes():
    state = _day_state(FIVE_ROLES)
    for voter in ("w1", "seer", "doc", "v1"):
        submit_vote(state, voter, "SKIP", 2, 1010)
    assert state["phase"] == "DAY"
    assert state["phase_version"] == 2


def test_day_ends_early_when_all_living_players_voted():
    state = _day_state(FIVE_ROLES)
    for voter in ("seer", "doc", "v1"):
        submit_vote(state, voter, "v2", 2, 1010)
    submit_vote(state, "w1", "SKIP", 2, 1010)
    submit_vote(state, "v2", "w1", 2, 1010)  # last living voter -> resolves immediately

    assert state["phase"] == "NIGHT"
    assert state["phase_version"] == 3
    assert state["day_count"] == 2
    assert state["phase_end_time"] == 1010 + NIGHT_DURATION_SECONDS
    assert state["day_votes"] == {}
    assert state["players"]["v2"]["alive"] is False  # 3 votes vs 1 SKIP vs 1


def test_early_day_end_with_all_skip_executes_nobody():
    state = _day_state(FIVE_ROLES)
    for voter in FIVE_ROLES:
        submit_vote(state, voter, "SKIP", 2, 1010)
    assert state["phase"] == "NIGHT"
    assert all(p["alive"] for p in state["players"].values())


def test_early_day_end_can_finish_the_game():
    state = _day_state(FIVE_ROLES)
    for voter in ("seer", "doc", "v1", "v2"):
        submit_vote(state, voter, "w1", 2, 1010)
    submit_vote(state, "w1", "SKIP", 2, 1010)
    assert state["phase"] == "ENDED"
    assert state["winner"] == "VILLAGER"


def test_vote_after_early_day_end_is_stale():
    state = _day_state(FIVE_ROLES)
    for voter in FIVE_ROLES:
        submit_vote(state, voter, "SKIP", 2, 1010)
    with pytest.raises(GameError) as exc:
        submit_vote(state, "v1", "SKIP", 2, 1011)
    assert exc.value.code == "PHASE_VERSION_CONFLICT"


# ===========================================================================
# 8. PlayerView Security Invariant (Role Privacy)
# ===========================================================================

def test_player_view_sanitizes_other_roles_during_game():
    state = {
        "room_id": "TEST",
        "phase": "NIGHT",
        "day_count": 1,
        "phase_version": 1,
        "phase_end_time": 1045,
        "players": {
            "p1": {"name": "Alice", "role": "WEREWOLF", "alive": True, "is_host": True},
            "p2": {"name": "Bob", "role": "SEER", "alive": True, "is_host": False},
            "p3": {"name": "Carol", "role": "DOCTOR", "alive": True, "is_host": False},
            "p4": {"name": "Dave", "role": "VILLAGER", "alive": True, "is_host": False},
        },
        "night_actions": empty_night_actions(),
    }
    # Bob (Seer) requests state
    view = build_player_view(state, "p2", 1000)
    assert view["me"]["role"] == "SEER"
    for p in view["players"]:
        if p["player_id"] == "p2":
            assert p["role"] == "SEER"
        else:
            # Strictly None for all other players!
            assert p["role"] is None


def test_player_view_werewolf_sees_fellow_werewolves():
    state = {
        "room_id": "TEST",
        "phase": "NIGHT",
        "day_count": 1,
        "phase_version": 1,
        "phase_end_time": 1045,
        "players": {
            "w1": {"name": "Wolf 1", "role": "WEREWOLF", "alive": True},
            "w2": {"name": "Wolf 2", "role": "WEREWOLF", "alive": True},
            "v1": {"name": "Villager", "role": "VILLAGER", "alive": True},
        },
        "night_actions": empty_night_actions(),
    }
    view = build_player_view(state, "w1", 1000)
    players_by_id = {p["player_id"]: p for p in view["players"]}
    assert players_by_id["w1"]["role"] == "WEREWOLF"
    assert players_by_id["w2"]["role"] == "WEREWOLF"  # Fellow wolf is visible!
    assert players_by_id["v1"]["role"] is None  # Other roles still hidden!


def test_player_view_reveals_all_roles_when_game_ended():
    state = {
        "room_id": "TEST",
        "phase": "ENDED",
        "winner": "VILLAGER",
        "players": {
            "w1": {"name": "Wolf", "role": "WEREWOLF", "alive": False},
            "doc": {"name": "Doc", "role": "DOCTOR", "alive": True},
            "v1": {"name": "Villager", "role": "VILLAGER", "alive": True},
        },
    }
    view = build_player_view(state, "v1", 1000)
    assert view["winner"] == "VILLAGER"
    for p in view["players"]:
        assert p["role"] is not None  # Everyone's role revealed!


# ===========================================================================
# 9. FastAPI HTTP Integration Tests (via AsyncClient & InMemoryStateStore)
# ===========================================================================

@pytest.fixture(autouse=True)
def setup_test_store():
    # Reset store to fresh InMemoryStateStore for each test
    from app import main as gm_main
    gm_main.store = InMemoryStateStore()
    yield gm_main.store


@pytest.mark.asyncio
async def test_api_health_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Liveness
        res_live = await client.get("/health/live")
        assert res_live.status_code == 200
        assert res_live.json()["status"] == "UP"
        assert res_live.json()["trace"][0]["service"] == "gamemaster"

        # 2. Readiness
        res_ready = await client.get("/health/ready")
        assert res_ready.status_code == 200
        assert res_ready.json()["status"] == "UP"


@pytest.mark.asyncio
async def test_api_full_game_lifecycle_integration():
    from app import main as gm_main
    store_ref = gm_main.store

    room_id = "HTTP"
    pids = ["p1", "p2", "p3", "p4", "p5"]
    players = {pid: {"player_id": pid, "name": f"Player {pid}", "is_host": pid == "p1"} for pid in pids}
    await store_ref.create_room(room_id, {"room_id": room_id, "phase": "WAITING", "players": players})
    for pid in pids:
        await store_ref.create_player_session(f"tok-{pid}", {"room_id": room_id, "player_id": pid})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Initialize Game
        init_res = await client.post(
            f"/internal/rooms/{room_id}/initialize",
            headers={"X-Request-ID": "req-init"}
        )
        assert init_res.status_code == 200
        assert init_res.json()["ok"] is True
        assert init_res.json()["data"]["status"] == "INITIALIZED"
        assert init_res.json()["request_id"] == "req-init"

        # 2. Get State for each player
        roles = {}
        for pid in pids:
            state_res = await client.get(
                f"/api/game/rooms/{room_id}/state",
                headers={"Authorization": f"Bearer tok-{pid}"}
            )
            assert state_res.status_code == 200
            data = state_res.json()["data"]
            assert data["phase"] == "NIGHT"
            roles[pid] = data["me"]["role"]
            assert data["me"]["player_id"] == pid
            # Other players' roles are null
            for other in data["players"]:
                if other["player_id"] != pid and roles[pid] != "WEREWOLF":
                    assert other["role"] is None

        # 3. Unauthorized access without token
        unauth_res = await client.get(f"/api/game/rooms/{room_id}/state")
        assert unauth_res.status_code == 401
        assert unauth_res.json()["error"]["code"] == "MISSING_TOKEN"

        # 4. Submit night actions
        by_role = {role: pid for pid, role in roles.items()}
        wolf_id = by_role["WEREWOLF"]
        doc_id = by_role["DOCTOR"]
        seer_id = by_role["SEER"]
        target = [pid for pid in pids if pid not in (wolf_id, doc_id, seer_id)][0]

        # Wolf attack
        wolf_res = await client.post(
            f"/api/game/rooms/{room_id}/night-actions",
            headers={"Authorization": f"Bearer tok-{wolf_id}"},
            json={"phase_version": 1, "action": "WEREWOLF_KILL", "target_id": target}
        )
        assert wolf_res.status_code == 200
        assert wolf_res.json()["data"]["status"] == "ACCEPTED"

        # Doctor protect
        doc_res = await client.post(
            f"/api/game/rooms/{room_id}/night-actions",
            headers={"Authorization": f"Bearer tok-{doc_id}"},
            json={"phase_version": 1, "action": "DOCTOR_PROTECT", "target_id": target}
        )
        assert doc_res.status_code == 200

        # Seer check (last living active role -> triggers early resolution!)
        seer_res = await client.post(
            f"/api/game/rooms/{room_id}/night-actions",
            headers={"Authorization": f"Bearer tok-{seer_id}"},
            json={"phase_version": 1, "action": "SEER_CHECK", "target_id": wolf_id}
        )
        assert seer_res.status_code == 200

        # Verify phase transitioned to DAY immediately
        state_after_night = (await client.get(
            f"/api/game/rooms/{room_id}/state",
            headers={"Authorization": f"Bearer tok-{seer_id}"}
        )).json()["data"]
        assert state_after_night["phase"] == "DAY"
        assert state_after_night["phase_version"] == 2
        # Seer sees their inspection result
        assert state_after_night["me"]["private_info"]["seer_result"]["result"] == "WEREWOLF"
        # Victim was saved by doctor -> nobody died
        assert state_after_night["me"]["alive"] is True


@pytest.mark.asyncio
async def test_api_day_ends_as_soon_as_everyone_votes():
    from app import main as gm_main
    store_ref = gm_main.store

    room_id = "VOTE"
    roles = {"p1": "WEREWOLF", "p2": "SEER", "p3": "DOCTOR", "p4": "VILLAGER", "p5": "VILLAGER"}
    players = {
        pid: {"player_id": pid, "name": pid, "is_host": pid == "p1", "role": role, "alive": True}
        for pid, role in roles.items()
    }
    await store_ref.create_room(room_id, {
        "room_id": room_id, "phase": "DAY", "phase_version": 2, "day_count": 1,
        "phase_end_time": 4_000_000_000,  # far future: only the votes can end this day
        "players": players, "night_actions": empty_night_actions(), "day_votes": {},
    })
    for pid in roles:
        await store_ref.create_player_session(f"tok-{pid}", {"room_id": room_id, "player_id": pid})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for pid in roles:
            target = "SKIP" if pid == "p1" else "p1"
            res = await client.post(
                f"/api/game/rooms/{room_id}/vote",
                headers={"Authorization": f"Bearer tok-{pid}"},
                json={"phase_version": 2, "target_id": target},
            )
            assert res.status_code == 200
            assert res.json()["data"]["status"] == "VOTE_CAST"

        final = (await client.get(
            f"/api/game/rooms/{room_id}/state",
            headers={"Authorization": "Bearer tok-p2"},
        )).json()["data"]
    assert final["phase"] == "ENDED"
    assert final["winner"] == "VILLAGER"
