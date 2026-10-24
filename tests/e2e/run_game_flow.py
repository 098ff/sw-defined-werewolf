"""
End-to-end game flow against a running stack (docker compose or the K8s cluster).

Plays one deterministic 5-player game through the gateway and checks, at every step,
the rubric-critical guarantees: standard envelope, >= 2 containers in the trace,
chat channel permissions and role hiding.

    docker compose -f docker-compose.dev.yml up --build -d
    python tests/e2e/run_game_flow.py                         # http://localhost:8080
    python tests/e2e/run_game_flow.py --base-url http://192.168.0.240

Day phase is skipped via the demo endpoint (needs DEMO_MODE on gamemaster and the
gateway proxying /api/demo/*). If that is unavailable the script waits for the real
60s timer instead, so it still completes, just slower.

Spec: docs/03-team-workflow.md section 4.4, contracts/api-contract.md
"""
import argparse
import sys
import time
from typing import Any, Dict, List, Optional

import httpx

DEFAULT_DEMO_SECRET = "sds-werewolf-demo-secret"
NAMES = ["Alice", "Bob", "Carol", "Dave", "Eve"]


class E2EFailure(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise E2EFailure(message)


class GameClient:
    def __init__(self, base_url: str, demo_secret: str, gamemaster_url: Optional[str]):
        self.http = httpx.Client(base_url=base_url, timeout=10.0)
        self.demo_secret = demo_secret
        self.gamemaster_url = gamemaster_url
        self.room_id = ""
        self.tokens: Dict[str, str] = {}   # name -> token
        self.ids: Dict[str, str] = {}      # name -> player_id

    def call(self, method: str, path: str, name: Optional[str] = None, expect: int = 200,
             json: Any = None, step: str = "") -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.tokens[name]}"} if name else {}
        resp = self.http.request(method, path, json=json, headers=headers)
        try:
            body = resp.json()
        except ValueError:
            raise E2EFailure(f"{step or path}: non-JSON response ({resp.status_code}): {resp.text[:200]}")
        check(resp.status_code == expect,
              f"{step or path}: expected HTTP {expect}, got {resp.status_code}: {body}")
        check({"ok", "request_id", "trace"} <= body.keys(), f"{step or path}: envelope keys missing: {body}")
        check(body["ok"] is (expect < 400), f"{step or path}: ok flag mismatch: {body}")
        self.check_trace(body["trace"], step or path)
        return body

    @staticmethod
    def check_trace(trace: List[Dict[str, str]], step: str) -> None:
        check(len(trace) >= 2, f"{step}: request touched only {len(trace)} container(s): {trace}")
        check(trace[0]["service"] == "gateway", f"{step}: first hop is not gateway: {trace}")
        hops = " -> ".join(f"{t['service']}({t['node']})" for t in trace)
        print(f"    trace: {hops}")

    def state(self, name: str) -> Dict[str, Any]:
        return self.call("GET", f"/api/game/rooms/{self.room_id}/state", name, step=f"state[{name}]")["data"]

    def chat(self, name: str, channel: str, text: str, expect: int = 200) -> None:
        self.call("POST", f"/api/chat/rooms/{self.room_id}/messages", name, expect,
                  json={"channel": channel, "text": text}, step=f"chat {channel}[{name}]")

    def visible_channels(self, name: str) -> set:
        data = self.call("GET", f"/api/chat/rooms/{self.room_id}/messages", name, step=f"read chat[{name}]")["data"]
        return {m["channel"] for m in data["messages"]}

    def force_next_phase(self, viewer: str) -> None:
        """Skips the current timer via the demo endpoint, falling back to waiting it out."""
        before = self.state(viewer)
        path = f"/api/demo/rooms/{self.room_id}/force-next"
        headers = {"X-Demo-Secret": self.demo_secret}
        targets = [("gateway", self.http.base_url.join(path))]
        if self.gamemaster_url:
            targets.append(("gamemaster", f"{self.gamemaster_url}{path}"))
        for label, url in targets:
            try:
                resp = httpx.post(url, headers=headers, timeout=10.0)
            except httpx.RequestError:
                continue
            if resp.status_code == 200:
                print(f"    skipped timer via {label} demo endpoint")
                return
        wait = max(0, before["phase_end_time"] - before.get("server_time", int(time.time()))) + 1
        print(f"    demo endpoint unavailable; waiting {wait}s for the real timer")
        time.sleep(wait)


def wait_for_phase(game: GameClient, viewer: str, phase: str, timeout: float = 90.0) -> Dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        view = game.state(viewer)
        if view["phase"] == phase:
            return view
        time.sleep(2)
    raise E2EFailure(f"phase did not become {phase} within {timeout}s")


def run(game: GameClient) -> None:
    host = NAMES[0]

    print("[1] Frontend page load goes through gateway")
    resp = game.http.get("/")
    check(resp.status_code == 200, f"GET / returned {resp.status_code}")

    print("[2] Host creates room")
    data = game.call("POST", "/api/lobby/rooms", json={"name": host}, step="create room")["data"]
    game.room_id = data["room_id"]
    game.tokens[host], game.ids[host] = data["player_token"], data["player_id"]
    check(data["is_host"] is True, "creator should be host")
    print(f"    room {game.room_id}")

    print("[3] Host cannot start with < 4 players")
    game.call("POST", f"/api/lobby/rooms/{game.room_id}/start", host, expect=400, step="early start")

    print("[4] Four players join")
    for name in NAMES[1:]:
        data = game.call("POST", f"/api/lobby/rooms/{game.room_id}/join", json={"name": name},
                         step=f"join[{name}]")["data"]
        game.tokens[name], game.ids[name] = data["player_token"], data["player_id"]
    lobby = game.call("GET", f"/api/lobby/rooms/{game.room_id}", host, step="lobby state")["data"]
    check(len(lobby["players"]) == 5, f"lobby should list 5 players: {lobby}")

    print("[5] Non-host cannot start; host starts")
    game.call("POST", f"/api/lobby/rooms/{game.room_id}/start", NAMES[1], expect=403, step="non-host start")
    game.call("POST", f"/api/lobby/rooms/{game.room_id}/start", host, step="start")
    game.call("POST", f"/api/lobby/rooms/{game.room_id}/join", json={"name": "Late"}, expect=409,
              step="join after start")

    print("[6] Every player sees only their own role")
    roles: Dict[str, str] = {}
    for name in NAMES:
        view = game.state(name)
        check(view["phase"] == "NIGHT", f"game should start at NIGHT: {view['phase']}")
        roles[name] = view["me"]["role"]
        for p in view["players"]:
            if p["player_id"] != game.ids[name] and view["me"]["role"] != "WEREWOLF":
                check(p["role"] is None, f"{name} can see {p['name']}'s role")
    by_role: Dict[str, List[str]] = {}
    for name, role in roles.items():
        by_role.setdefault(role, []).append(name)
    print(f"    roles: {roles}")
    check(len(by_role.get("WEREWOLF", [])) == 1 and len(by_role.get("VILLAGER", [])) == 2,
          f"unexpected 5-player role split: {by_role}")
    wolf, doctor, seer = by_role["WEREWOLF"][0], by_role["DOCTOR"][0], by_role["SEER"][0]
    victim, survivor = by_role["VILLAGER"]

    print("[7] Night chat permissions")
    game.chat(wolf, "WOLF", "let's get the villager")
    game.chat(seer, "WOLF", "let me in", expect=403)
    game.chat(seer, "PUBLIC", "is it day yet?", expect=403)
    check("WOLF" in game.visible_channels(wolf), "wolf should read WOLF chat")
    check("WOLF" not in game.visible_channels(seer), "seer must not read WOLF chat")

    print("[8] Night actions (all submitted -> night resolves early)")
    phase_version = game.state(wolf)["phase_version"]
    game.call("POST", f"/api/game/rooms/{game.room_id}/night-actions", seer,
              json={"phase_version": phase_version, "action": "SEER_CHECK", "target_id": game.ids[wolf]},
              step="seer check")
    game.call("POST", f"/api/game/rooms/{game.room_id}/night-actions", doctor,
              json={"phase_version": phase_version, "action": "DOCTOR_PROTECT", "target_id": game.ids[doctor]},
              step="doctor protect")
    game.call("POST", f"/api/game/rooms/{game.room_id}/night-actions", wolf,
              json={"phase_version": phase_version, "action": "WEREWOLF_KILL", "target_id": game.ids[victim]},
              step="wolf kill")

    print("[9] Day: victim died, seer learned the truth")
    view = wait_for_phase(game, seer, "DAY")
    check(view["me"]["private_info"].get("seer_result", {}).get("result") == "WEREWOLF",
          f"seer result missing: {view['me']}")
    check(not game.state(victim)["me"]["alive"], f"{victim} should be dead after the night")

    print("[10] Day chat permissions")
    game.chat(survivor, "PUBLIC", f"I think {wolf} is the wolf")
    game.chat(victim, "PUBLIC", "I'm a ghost", expect=403)
    game.chat(victim, "DEAD", "boo")
    check("DEAD" in game.visible_channels(victim), "dead player should read DEAD chat")
    check("DEAD" not in game.visible_channels(survivor), "living player must not read DEAD chat")

    print("[11] Vote out the werewolf")
    phase_version = view["phase_version"]
    for name in (doctor, seer, survivor):
        game.call("POST", f"/api/game/rooms/{game.room_id}/vote", name,
                  json={"phase_version": phase_version, "target_id": game.ids[wolf]}, step=f"vote[{name}]")
    # Dead vote must be checked before the last living ballot, which ends the day early
    game.call("POST", f"/api/game/rooms/{game.room_id}/vote", victim, expect=403,
              json={"phase_version": phase_version, "target_id": "SKIP"}, step="dead vote")
    game.call("POST", f"/api/game/rooms/{game.room_id}/vote", wolf,
              json={"phase_version": phase_version, "target_id": "SKIP"}, step=f"vote[{wolf}]")

    print("[12] Last ballot ends the day -> villagers win, all roles revealed")
    view = wait_for_phase(game, seer, "ENDED")
    check(view["winner"] == "VILLAGER", f"villagers should win: {view['winner']}")
    check(all(p["role"] for p in view["players"]), "all roles should be revealed after the game")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8080", help="gateway URL")
    parser.add_argument("--demo-secret", default=DEFAULT_DEMO_SECRET)
    parser.add_argument("--gamemaster-url", default=None,
                        help="optional direct gamemaster URL for the demo endpoint if gateway does not proxy it")
    args = parser.parse_args()

    game = GameClient(args.base_url, args.demo_secret, args.gamemaster_url)
    try:
        run(game)
    except E2EFailure as exc:
        print(f"\nE2E FAILED: {exc}")
        return 1
    except httpx.RequestError as exc:
        print(f"\nE2E FAILED: cannot reach {args.base_url}: {exc}")
        return 1
    print("\nE2E PASSED: full game completed, every request touched >= 2 containers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
