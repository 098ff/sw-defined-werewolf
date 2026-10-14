# AI Agent Guide — Role 4: GameMaster Service Lead

> **Role Focus:** Authoritative Game Engine, Role Shuffling, FSM Phase Transitions, Night/Day Resolution Algorithms, Win Conditions, and Sanitized `PlayerView` Generation.  
> **Master Context:** Read [00-agent-system-prompt.md](00-agent-system-prompt.md), [02-game-rules-and-ux.md](../02-game-rules-and-ux.md), and [api-contract.md](../../contracts/api-contract.md).

---

## 1. Role Scope & Owned Files

As the GameMaster Service Lead, you develop the core business logic, rule authority, and mathematical state transitions of the Werewolf game.

### Files You Own
- `services/gamemaster/` (FastAPI application, Dockerfile, requirements.txt)
- `tests/unit/test_gamemaster.py` (Rule unit tests and FSM edge cases)

### Files You Must NOT Modify
- Do not handle pre-game player registration (owned by `services/lobby/`).
- Do not modify chat logic (owned by `services/chat/`).
- Do not modify the `StateStore` interface (owned by Role 5).

---

## 2. Technical Specifications & Endpoints

### 2.1 API Endpoints to Implement

| Method | Path | Auth Required | Description |
|---|---|---|---|
| `POST` | `/internal/rooms/{room_id}/initialize` | Internal Call | Invoked by Lobby upon game start. Shuffles and assigns roles according to player count, transitions to `NIGHT`, sets `phase_end_time = Redis TIME + 45s`. |
| `GET` | `/api/game/rooms/{room_id}/state` | Bearer Token | Executes `advance_if_expired()` on server clock, sanitizes internal state, and returns a tailored `PlayerView` for the requesting player. |
| `POST` | `/api/game/rooms/{room_id}/night-actions` | Bearer Token | Submits night actions (Werewolf attack, Doctor save, Seer inspect). Rejects dead players or invalid targets. |
| `POST` | `/api/game/rooms/{room_id}/vote` | Bearer Token | Submits day ballot (player ID or `SKIP`). Idempotent for identical votes; rejects changing vote with `409 ACTION_ALREADY_SUBMITTED`. |
| `POST` | `/api/demo/rooms/{room_id}/force-next` | Demo Secret | Manually triggers immediate phase resolution for demo acceleration. |
| `GET` | `/health/live` & `/health/ready` | None | Kubernetes readiness and liveness probes. |

---

## 3. Core Algorithms & Game Logic

### 3.1 Role Assignment Algorithm
Roles are assigned randomly when `initialize` is triggered:
- **4 Players:** `[WEREWOLF, DOCTOR, SEER, VILLAGER]`
- **5 Players:** `[WEREWOLF, DOCTOR, SEER, VILLAGER, VILLAGER]`
- **6 Players:** `[WEREWOLF, WEREWOLF, DOCTOR, SEER, VILLAGER, VILLAGER]`

### 3.2 Night Phase Resolution Pipeline
Executed when the 45-second timer expires or all living active role holders have submitted:
1. **Werewolf Tally:** Find candidate with strict majority of werewolf votes. If tied or no votes, victim is `None`.
2. **Doctor Save:** If Doctor target matches victim, victim survives.
3. **Casualty Applied:** If victim survives, casualty is `None`. Otherwise, victim's `alive = false`.
4. **Seer Result:** Record alignment (`WEREWOLF` or `GOOD`) into `night_actions.seer_result_by_player[seer_id]`.
5. **Win Condition Check:**
   - If wolves == 0 $\rightarrow$ Villagers Win (`phase = ENDED`, `winner = VILLAGER`).
   - If wolves $\ge$ good $\rightarrow$ Werewolves Win (`phase = ENDED`, `winner = WEREWOLF`).
   - Otherwise $\rightarrow$ Advance to `DAY` (`phase_end_time = Redis TIME + 60s`, clear night actions).

### 3.3 Day Phase & Voting Resolution Pipeline
Executed when the 60-second timer expires:
1. Count ballots from living players.
2. If `Total Ballots == 0` or `SKIP >= highest_candidate_votes`, no execution occurs.
3. If there is a tie for highest votes between candidates, no execution occurs.
4. If a single candidate has strictly more votes than any other and more than `SKIP`, that candidate is executed (`alive = false`).
5. **Win Condition Check:** Evaluate win conditions; if game continues, advance to `NIGHT` (`phase_end_time = Redis TIME + 45s`, clear day votes).

### 3.4 PlayerView Sanitizer (Strict Security Invariant)
**NEVER return `InternalRoomState` directly to the client.** The `GET /state` endpoint must sanitize the state based on the caller's identity:
- `me.role` $\rightarrow$ Caller's actual role.
- `me.private_info` $\rightarrow$ Seer inspection results (if caller is Seer).
- `players[*].role` $\rightarrow$ MUST be `null` for all other players while the game is ongoing!
  - **Exception 1:** If caller is `WEREWOLF`, they can see which other players are `WEREWOLF`.
  - **Exception 2:** When `phase == ENDED`, all roles are exposed to everyone.

---

## 4. Local Development & Testing Instructions

You can develop and unit test all game logic **without Docker, Redis, or Kubernetes** using `pytest`.

### 4.1 Running with `InMemoryStateStore`
```bash
cd services/gamemaster
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export STATE_STORE_BACKEND=in_memory
uvicorn app.main:app --port 8002 --reload
```

### 4.2 Unit Testing Game Rules (`tests/unit/test_gamemaster.py`)
```python
import pytest
from app.engine import resolve_night, resolve_day, check_win_condition

def test_doctor_saves_victim():
    players = {
        "p1": {"role": "WEREWOLF", "alive": True},
        "p2": {"role": "DOCTOR", "alive": True},
        "p3": {"role": "VILLAGER", "alive": True}
    }
    night_actions = {
        "wolf_votes": {"p1": "p3"},
        "doctor_target": "p3"
    }
    victim, announcement = resolve_night(players, night_actions)
    assert victim is None  # Doctor successfully saved victim!
    assert players["p3"]["alive"] is True

def test_win_condition_wolves_equal_good():
    players = {
        "p1": {"role": "WEREWOLF", "alive": True},
        "p2": {"role": "VILLAGER", "alive": True}
    }
    winner = check_win_condition(players)
    assert winner == "WEREWOLF"  # 1 wolf >= 1 villager -> Wolf wins!
```

Run test suite:
```bash
pytest tests/unit/test_gamemaster.py
```

---

## 5. Ready-to-Use Agent Prompt

```text
You are acting as the GameMaster Service Engineer (Role 4) for the Werewolf SDS project.
Your task is to build services/gamemaster/app and tests/unit/test_gamemaster.py.
Follow docs/roles/04-role-gamemaster.md, docs/02-game-rules-and-ux.md, and contracts/api-contract.md.
Implement the state machine, role assignment (4-6 players), night resolution (werewolf majority, doctor save, seer inspect),
day vote resolution (majority vs SKIP, tie handling), win condition checks, and the PlayerView sanitizer.
```
