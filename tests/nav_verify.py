"""Headless verification for the AI door-crossing / freeze bug.

Drives a single ally Agent straight toward the enemy spawn (right room) by
replicating the `update_agent` advance branch without combat, on the SMALL
match map (2x2). We assert:
  * the agent actually crosses the door (x > 27.5, into the right room)
  * it reaches close to the goal (final_d < 6.0)
  * it never freezes: no run of > 1.0s with no real movement.
"""

import math
import random
import sys

import config as C
from engine import build_arena
from match import Match
from ai import _repath, _follow_path

DT = 1.0 / 60.0
SECONDS = 30.0
STEPS = int(SECONDS / DT)


def run_one(seed: int, tune_move: float) -> dict:
    gmap = build_arena(C.MATCH_TILES_X, C.MATCH_TILES_Y,
                       C.MATCH_ROOM_W, C.MATCH_ROOM_H)
    rng = random.Random(seed)
    m = Match(gmap, random.Random(seed), "normal")

    # pick one ally (team 0, not player)
    ally = next(a for a in m.agents if a.team == 0 and not a.is_player)
    goal = m.spawns[1]  # enemy spawn in the far (right) room

    last_x, last_y = ally.x, ally.y
    last_move_t = 0.0
    max_gap = 0.0
    crossed = False
    t = 0.0

    for _ in range(STEPS):
        if not ally.alive:
            break
        _repath(m, ally, goal[0], goal[1], rng)
        _follow_path(m, ally, DT, C.AI_MOVE_SPEED * tune_move)

        moved = math.hypot(ally.x - last_x, ally.y - last_y)
        if moved > 0.02:
            gap = t - last_move_t
            if gap > max_gap:
                max_gap = gap
            last_move_t = t
            last_x, last_y = ally.x, ally.y
        if ally.x > 27.5:
            crossed = True
        t += DT

    final_d = math.hypot(ally.x - goal[0], ally.y - goal[1])
    return dict(crossed=crossed, final_d=final_d, max_gap=max_gap,
                end_x=ally.x, end_y=ally.y, alive=ally.alive)


def main():
    tune_move = C.AI_PRESETS["normal"]["move_mul"]
    results = []
    for seed in range(8):
        r = run_one(seed, tune_move)
        results.append((seed, r))

    print(f"{'seed':>4}  {'cross':>5}  {'final_d':>7}  {'max_gap':>7}  "
          f"{'end_x':>6}  {'end_y':>6}  alive")
    all_ok = True
    for seed, r in results:
        ok = r["crossed"] and r["final_d"] < 6.0 and r["max_gap"] < 1.0
        all_ok = all_ok and ok
        print(f"{seed:>4}  {str(r['crossed']):>5}  {r['final_d']:>7.2f}  "
              f"{r['max_gap']:>7.2f}  {r['end_x']:>6.2f}  {r['end_y']:>6.2f}  "
              f"{r['alive']}  {'OK' if ok else 'FAIL'}")

    print()
    print("ALL OK" if all_ok else "SOME FAILED")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
