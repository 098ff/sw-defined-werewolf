import time

def get_base_players():
    return [
        {"player_id": "p1", "name": "Alice", "role": "WEREWOLF", "alive": True, "is_host": True},
        {"player_id": "p2", "name": "Bob",   "role": "SEER",     "alive": True, "is_host": False},
        {"player_id": "p3", "name": "Carol", "role": "DOCTOR",   "alive": True, "is_host": False},
        {"player_id": "p4", "name": "Dave",  "role": "VILLAGER", "alive": True, "is_host": False},
        {"player_id": "p5", "name": "Eve",   "role": "VILLAGER", "alive": True, "is_host": False}
    ]

SCENARIOS = {
    "standard_night": {
        "room_id": "WOLF",
        "phase": "NIGHT",
        "day_count": 1,
        "phase_version": 1,
        "phase_end_time": int(time.time()) + 45,
        "winner": None,
        "announcement": "Night 1 has begun. Close your eyes.",
        "me": {"player_id": "p1", "name": "Alice", "role": "WEREWOLF", "alive": True, "is_host": True},
        "players": [
            {"player_id": "p1", "name": "Alice", "role": "WEREWOLF", "alive": True, "is_host": True},
            {"player_id": "p2", "name": "Bob",   "role": None,       "alive": True, "is_host": False},
            {"player_id": "p3", "name": "Carol", "role": None,       "alive": True, "is_host": False},
            {"player_id": "p4", "name": "Dave",  "role": None,       "alive": True, "is_host": False},
            {"player_id": "p5", "name": "Eve",   "role": None,       "alive": True, "is_host": False}
        ]
    },
    "seer_inspection": {
        "room_id": "WOLF",
        "phase": "NIGHT",
        "day_count": 1,
        "phase_version": 2,
        "phase_end_time": int(time.time()) + 45,
        "winner": None,
        "announcement": "Seer inspection completed.",
        "me": {
            "player_id": "p2",
            "name": "Bob",
            "role": "SEER",
            "alive": True,
            "is_host": False,
            "private_info": {"seer_result": {"target_id": "p1", "result": "WEREWOLF"}}
        },
        "players": [
            {"player_id": "p1", "name": "Alice", "role": None, "alive": True, "is_host": True},
            {"player_id": "p2", "name": "Bob",   "role": "SEER", "alive": True, "is_host": False},
            {"player_id": "p3", "name": "Carol", "role": None, "alive": True, "is_host": False},
            {"player_id": "p4", "name": "Dave",  "role": None, "alive": True, "is_host": False},
            {"player_id": "p5", "name": "Eve",   "role": None, "alive": True, "is_host": False}
        ]
    },
    "day_discussion": {
        "room_id": "WOLF",
        "phase": "DAY",
        "day_count": 1,
        "phase_version": 3,
        "phase_end_time": int(time.time()) + 60,
        "winner": None,
        "announcement": "Sun rises. Dave was attacked during the night and died.",
        "me": {"player_id": "p1", "name": "Alice", "role": "WEREWOLF", "alive": True, "is_host": True},
        "players": [
            {"player_id": "p1", "name": "Alice", "role": "WEREWOLF", "alive": True, "is_host": True},
            {"player_id": "p2", "name": "Bob",   "role": None,       "alive": True, "is_host": False},
            {"player_id": "p3", "name": "Carol", "role": None,       "alive": True, "is_host": False},
            {"player_id": "p4", "name": "Dave",  "role": None,       "alive": False, "is_host": False},
            {"player_id": "p5", "name": "Eve",   "role": None,       "alive": True, "is_host": False}
        ]
    },
    "vote_tie_no_execution": {
        "room_id": "WOLF",
        "phase": "NIGHT",
        "day_count": 2,
        "phase_version": 4,
        "phase_end_time": int(time.time()) + 45,
        "winner": None,
        "announcement": "The village vote was tied! Nobody was executed today.",
        "me": {"player_id": "p1", "name": "Alice", "role": "WEREWOLF", "alive": True, "is_host": True},
        "players": [
            {"player_id": "p1", "name": "Alice", "role": "WEREWOLF", "alive": True, "is_host": True},
            {"player_id": "p2", "name": "Bob",   "role": None,       "alive": True, "is_host": False},
            {"player_id": "p3", "name": "Carol", "role": None,       "alive": True, "is_host": False},
            {"player_id": "p4", "name": "Dave",  "role": None,       "alive": False, "is_host": False},
            {"player_id": "p5", "name": "Eve",   "role": None,       "alive": True, "is_host": False}
        ]
    },
    "vote_skip_majority": {
        "room_id": "WOLF",
        "phase": "NIGHT",
        "day_count": 2,
        "phase_version": 4,
        "phase_end_time": int(time.time()) + 45,
        "winner": None,
        "announcement": "The village voted to SKIP execution today.",
        "me": {"player_id": "p1", "name": "Alice", "role": "WEREWOLF", "alive": True, "is_host": True},
        "players": [
            {"player_id": "p1", "name": "Alice", "role": "WEREWOLF", "alive": True, "is_host": True},
            {"player_id": "p2", "name": "Bob",   "role": None,       "alive": True, "is_host": False},
            {"player_id": "p3", "name": "Carol", "role": None,       "alive": True, "is_host": False},
            {"player_id": "p4", "name": "Dave",  "role": None,       "alive": False, "is_host": False},
            {"player_id": "p5", "name": "Eve",   "role": None,       "alive": True, "is_host": False}
        ]
    },
    "game_ended_villagers": {
        "room_id": "WOLF",
        "phase": "ENDED",
        "day_count": 2,
        "phase_version": 5,
        "phase_end_time": int(time.time()),
        "winner": "VILLAGER",
        "announcement": "All werewolves eliminated! Villagers win the game!",
        "me": {"player_id": "p2", "name": "Bob", "role": "SEER", "alive": True, "is_host": False},
        "players": [
            {"player_id": "p1", "name": "Alice", "role": "WEREWOLF", "alive": False, "is_host": True},
            {"player_id": "p2", "name": "Bob",   "role": "SEER",     "alive": True,  "is_host": False},
            {"player_id": "p3", "name": "Carol", "role": "DOCTOR",   "alive": True,  "is_host": False},
            {"player_id": "p4", "name": "Dave",  "role": "VILLAGER", "alive": False, "is_host": False},
            {"player_id": "p5", "name": "Eve",   "role": "VILLAGER", "alive": True,  "is_host": False}
        ]
    },
    "game_ended_werewolves": {
        "room_id": "WOLF",
        "phase": "ENDED",
        "day_count": 2,
        "phase_version": 5,
        "phase_end_time": int(time.time()),
        "winner": "WEREWOLF",
        "announcement": "Werewolves equal or outnumber good players! Werewolves win!",
        "me": {"player_id": "p1", "name": "Alice", "role": "WEREWOLF", "alive": True, "is_host": True},
        "players": [
            {"player_id": "p1", "name": "Alice", "role": "WEREWOLF", "alive": True,  "is_host": True},
            {"player_id": "p2", "name": "Bob",   "role": "SEER",     "alive": False, "is_host": False},
            {"player_id": "p3", "name": "Carol", "role": "DOCTOR",   "alive": False, "is_host": False},
            {"player_id": "p4", "name": "Dave",  "role": "VILLAGER", "alive": False, "is_host": False},
            {"player_id": "p5", "name": "Eve",   "role": "VILLAGER", "alive": True,  "is_host": False}
        ]
    }
}
