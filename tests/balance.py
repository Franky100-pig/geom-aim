"""Balance probe for 3v3 versus.

Models the human player as an AI bot of a chosen skill (so we can test a
"mirror" 3v3 and also a "weak player" 3v3), then measures team-0 (player+
2 allies) win rate over many matches.

Usage:
  python3 tests/balance.py                 # normal enemies, mirror player
  python3 tests/balance.py normal weak      # normal enemies, weak player
  python3 tests/balance.py easy            # easy enemies, mirror player
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random

import config as C
from engine import build_arena, Camera
from match import Match, update_agent
from weapons import match_weapon

DT = 1.0 / 60.0
MAX_MATCH_SECONDS = 600.0
MAX_STEPS = int(MAX_MATCH_SECONDS / DT)


def run_match(seed: int, enemy_diff: str, player_diff: str):
    gmap = build_arena(C.MATCH_TILES_X, C.MATCH_TILES_Y,
                       C.MATCH_ROOM_W, C.MATCH_ROOM_H)
    rng = random.Random(seed)
    m = Match(gmap, rng, enemy_diff)

    cam = Camera(*m.spawns[0])

    if player_diff == "dead":
        # No human contribution: remove the player shadow -> pure 2 allies vs 3.
        m.agents = [a for a in m.agents if not a.is_player]
        m.player_agent = None
        m.player_dead = True
        steps = 0
        while not m.match_over and steps < MAX_STEPS:
            m.update(DT)
            steps += 1
        return m.score[0], m.score[1]

    # Turn the human shadow into an AI bot so we can simulate a player.
    p = m.player_agent
    p.is_player = False
    p.weapon = match_weapon("rifle")
    p.money = C.ECON_START          # sim-only: economy code expects .money

    if player_diff == "mirror":
        p_tune = dict(m.ally_tune)      # competent-teammate level
    else:
        base = C.AI_PRESETS[player_diff]
        p_tune = dict(reaction=base["reaction"], sigma=base["sigma"],
                      burst=base["burst"], strafe=base["strafe"],
                      move_mul=base["move_mul"])

    # Test-only patch: drive the player with its own tune. match.update calls
    # match.update_agent, so patch that name (no production code touched).
    orig = update_agent

    def patched(mm, a, dt, r, tune):
        if a is p:
            return orig(mm, a, dt, r, p_tune)
        return orig(mm, a, dt, r, tune)

    import match as _match_mod
    _match_mod.update_agent = patched

    steps = 0
    while not m.match_over and steps < MAX_STEPS:
        # keep cam on the player so sync_player() is a no-op (player stays AI-driven)
        cam.x, cam.y = p.x, p.y
        m.sync_player(cam)
        m.update(DT)
        steps += 1
    return m.score[0], m.score[1]


def main():
    enemy_diff = sys.argv[1] if len(sys.argv) > 1 else "normal"
    player_diff = sys.argv[2] if len(sys.argv) > 2 else enemy_diff
    if player_diff == "mirror":
        player_diff = enemy_diff
    n = 24
    t0 = t1 = 0
    for s in range(n):
        a, b = run_match(s * 7 + 1, enemy_diff, player_diff)
        if a > b:
            t0 += 1
        elif b > a:
            t1 += 1
    print(f"enemy={enemy_diff} player={player_diff}  matches={n}")
    print(f"  team0 (you+allies) wins: {t0}/{n}  ({100*t0/n:.0f}%)")
    print(f"  team1 (enemies)    wins: {t1}/{n}  ({100*t1/n:.0f}%)")
    print(f"  draws: {n - t0 - t1}")


if __name__ == "__main__":
    main()
