"""Full-loop live smoke for 3v3: run a real Match with the live update loop and
confirm ally AI traverses the map (crosses the door into the enemy room) and the
match advances without freezing or crashing."""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import random

import config as C
from engine import build_arena, Camera
from match import Match

DT = 1.0 / 60.0
SECONDS = 40.0
STEPS = int(SECONDS / DT)


def main():
    gmap = build_arena(C.MATCH_TILES_X, C.MATCH_TILES_Y,
                       C.MATCH_ROOM_W, C.MATCH_ROOM_H)
    rng = random.Random(7)
    m = Match(gmap, rng, "normal")

    cam = Camera(*m.spawns[0])
    # skip buy phase, start fighting immediately
    m.state = "live"
    m.timer = C.MATCH_ROUND_TIME

    allies = [a for a in m.agents if a.team == 0 and not a.is_player]
    start = {id(a): (a.x, a.y) for a in allies}

    crossed = [False] * len(allies)
    max_gap = [0.0] * len(allies)
    cur_gap = [0.0] * len(allies)
    last_seen = [(a.x, a.y) for a in allies]

    for step in range(STEPS):
        t = step * DT
        m.sync_player(cam)
        m.update(DT)
        for i, a in enumerate(allies):
            # only count freezes during live combat while the ally is alive;
            # buy phase / round-end / death are legitimate immobility.
            if not a.alive or m.state != "live":
                cur_gap[i] = 0.0
                last_seen[i] = (a.x, a.y)
                continue
            if a.x > 27.5:
                crossed[i] = True
            moved = math.hypot(a.x - last_seen[i][0], a.y - last_seen[i][1])
            if moved > 0.02:
                max_gap[i] = max(max_gap[i], cur_gap[i])
                cur_gap[i] = 0.0
                last_seen[i] = (a.x, a.y)
            else:
                cur_gap[i] += DT

    disp = [math.hypot(a.x - start[id(a)][0], a.y - start[id(a)][1])
            for a in allies]
    print(f"allies={len(allies)}  crossed_door={sum(crossed)}/{len(allies)}")
    print(f"max displacement={max(disp):.1f}  min displacement={min(disp):.1f}")
    print(f"worst live-combat freeze gap={max(max_gap):.2f}s")
    print(f"round state after sim: {m.state}  score={m.score}  "
          f"rounds={m.round_no}")
    ok = (sum(crossed) >= 1 and max(disp) > 15.0 and max(max_gap) < 1.5)
    print("SMOKE OK" if ok else "SMOKE FAIL")


if __name__ == "__main__":
    main()
