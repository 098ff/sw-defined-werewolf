"""
Plays one scripted 5-player game against the GameMaster API and prints each step.

  In-process (no server, no Redis):
      python services/gamemaster/play_demo.py

  Against a running gamemaster backed by Redis:
      python services/gamemaster/play_demo.py --url http://localhost:8002 --redis redis://localhost:6379

The script plays the Lobby's part: it writes the WAITING room and player sessions
into the StateStore, then drives everything else through HTTP.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]

import httpx  # noqa: E402

from common.state_store import InMemoryStateStore, RedisStateStore  # noqa: E402

ROOM = "DEMO"
NAMES = ["Alice", "Bob", "Carol", "Dave", "Eve"]


def show(title, body):
    print(f"\n=== {title}")
    print(json.dumps(body, indent=2))


async def seed(store):
    players = {f"p{i}": {"player_id": f"p{i}", "name": n, "is_host": i == 1} for i, n in enumerate(NAMES, 1)}
    if await store.get_room(ROOM) is not None:
        # Re-runs against Redis start from a fresh WAITING room
        await store.update_room(ROOM, lambda s: {"room_id": ROOM, "phase": "WAITING", "players": players,
                                                  "version": s.get("version", 0)})
    else:
        await store.create_room(ROOM, {"room_id": ROOM, "phase": "WAITING", "players": players})
    for pid in players:
        await store.create_player_session(f"tok-{pid}", {"room_id": ROOM, "player_id": pid})


async def play(client, demo_secret):
    h = lambda pid: {"Authorization": f"Bearer tok-{pid}"}  # noqa: E731
    state = lambda pid: client.get(f"/api/game/rooms/{ROOM}/state", headers=h(pid))  # noqa: E731

    show("initialize", (await client.post(f"/internal/rooms/{ROOM}/initialize")).json())

    roles = {}
    for i in range(1, 6):
        view = (await state(f"p{i}")).json()["data"]
        roles[f"p{i}"] = view["me"]["role"]
    print("\nSecret roles (each player only sees their own):", roles)
    by_role = {}
    for pid, role in roles.items():
        by_role.setdefault(role, []).append(pid)
    wolf, doctor, seer = by_role["WEREWOLF"][0], by_role["DOCTOR"][0], by_role["SEER"][0]
    villagers = by_role["VILLAGER"]

    show(f"villager {villagers[0]} view - other roles must be null", (await state(villagers[0])).json()["data"]["players"])

    act = lambda pid, action, target: client.post(  # noqa: E731
        f"/api/game/rooms/{ROOM}/night-actions", headers=h(pid),
        json={"phase_version": 1, "action": action, "target_id": target})
    show(f"villager {villagers[0]} tries a night action (expect 403)", (await act(villagers[0], "WEREWOLF_KILL", seer)).json())
    show(f"wolf {wolf} kills {villagers[0]}", (await act(wolf, "WEREWOLF_KILL", villagers[0])).json()["data"])
    show(f"doctor {doctor} protects {villagers[1]}", (await act(doctor, "DOCTOR_PROTECT", villagers[1])).json()["data"])
    show(f"seer {seer} checks {wolf}", (await act(seer, "SEER_CHECK", wolf)).json()["data"])

    day = (await state(seer)).json()["data"]
    show("after night 1 (all acted -> night ends early)",
         {k: day[k] for k in ("phase", "phase_version", "announcement")} | {"seer_private_info": day["me"]["private_info"]})

    for pid in roles:
        if pid != wolf and pid != villagers[0]:
            await client.post(f"/api/game/rooms/{ROOM}/vote", headers=h(pid),
                              json={"phase_version": day["phase_version"], "target_id": wolf})
    print(f"\nEveryone alive except the wolf voted for {wolf}. Forcing the day timer to end...")
    show("force-next", (await client.post(f"/api/demo/rooms/{ROOM}/force-next",
                                          headers={"X-Demo-Secret": demo_secret})).json()["data"])

    final = (await state(villagers[1])).json()
    show("final state seen by a villager (all roles revealed)",
         {k: final["data"][k] for k in ("phase", "winner", "announcement", "players")})
    show("trace", final["trace"])


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Base URL of a running gamemaster (requires --redis)")
    parser.add_argument("--redis", help="Redis URL shared with that gamemaster")
    args = parser.parse_args()

    if args.url:
        if not args.redis:
            sys.exit("--url needs --redis so the script can seed the room the way the Lobby would")
        store = RedisStateStore(args.redis)
        await seed(store)
        async with httpx.AsyncClient(base_url=args.url) as client:
            await play(client, os.getenv("DEMO_SECRET", "sds-werewolf-demo-secret"))
        return

    from app import main as gm  # in-process: swap in a fresh in-memory store
    gm.store = InMemoryStateStore()
    gm.DEMO_MODE, gm.DEMO_SECRET = True, "local-secret"
    await seed(gm.store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gm.app), base_url="http://gm") as client:
        await play(client, "local-secret")


if __name__ == "__main__":
    asyncio.run(main())
