"""回归测试：3v3 新回合必须把玩家武器重置回默认（不再顺延上一把）。

Bug 1：玩家上一回合买了狙击并赢了，下一回合会自动带着狙击，而不是变回默认武器。
根因在 main._update_match：self.player.weapon 只在 start_match 设过一次，之后每帧又被
推回 player_agent.weapon；而 start_round 重置的是 player_agent，本地玩家的 Player.weapon
没人重置，于是永远顺延。修复是每回合开局把 self.player.weapon 同步回 agent 的默认武器。
"""

from __future__ import annotations

import math
import sys

import pygame

pygame.init()

import config as C  # noqa: E402
import engine  # noqa: E402
import main  # noqa: E402
import weapons  # noqa: E402
from match import Match  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name: str, ok: bool, detail: str = ""):
    if ok:
        PASS.append(name)
        print(f"  [ok]   {name}  {detail}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}  {detail}")


def _press(w: bool = False, a: bool = False, s: bool = False, d: bool = False):
    keys = [0] * 512
    if w: keys[pygame.K_w] = 1
    if a: keys[pygame.K_a] = 1
    if s: keys[pygame.K_s] = 1
    if d: keys[pygame.K_d] = 1
    return keys


def test_match_reset_contract():
    """Match.start_round 必须把玩家影子 Agent 的武器/库存重置回默认。"""
    gmap = engine.build_arena(C.MATCH_TILES_X, C.MATCH_TILES_Y,
                              C.MATCH_ROOM_W, C.MATCH_ROOM_H, cover=True)
    m = Match(gmap, __import__("random").Random(), "normal", None, mode="match")
    pa = m.player_agent
    default = pa.loadout[0]
    # 模拟"上一回合买了狙击"
    pa.weapon = weapons.MATCH_WEAPONS["awp"]
    pa.loadout = ["knife", "awp"] if "knife" in weapons.MATCH_WEAPONS else ["pistol", "awp"]
    pa.mags = {k: 1 for k in pa.loadout}
    # 开新回合
    m.start_round()
    check("start_round 重置玩家武器回默认", pa.weapon.key == default,
          f"预期 {default}，实际 {pa.weapon.key}")
    check("start_round 重置库存回单把默认枪", pa.loadout == [default],
          f"预期 [ {default} ]，实际 {pa.loadout}")


def test_game_round_carryover_fixed():
    """整体跑一帧 _update_match：上一回合的狙击不应顺延到下一回合。"""
    g = main.Game()
    g.start_match()                       # 建 3v3，默认武器（pistol/knife）
    g.match.player_agent.weapon = weapons.MATCH_WEAPONS["awp"]
    g.player.weapon = weapons.MATCH_WEAPONS["awp"]
    g.match.player_agent.loadout = (["knife", "awp"]
                                   if "knife" in weapons.MATCH_WEAPONS else ["pistol", "awp"])
    pre = g.player.weapon.key
    check("前置：玩家确实拿着狙击", pre == "awp", f"实际 {pre}")

    # 触发下一回合（round_no +1）并跑一帧 _update_match
    g.match.start_round()
    g._update_match(1 / 60)

    default = g.match.player_agent.loadout[0]
    check("新回合后玩家武器重置回默认", g.player.weapon.key == default,
          f"预期 {default}，实际 {g.player.weapon.key}")
    check("新回合后狙击不再顺延", g.player.weapon.key != "awp",
          f"实际 {g.player.weapon.key}")
    # 玩家与影子 Agent 必须一致（否则会被下一帧的推送覆盖）
    check("玩家武器与影子 Agent 一致",
          g.player.weapon.key == g.match.player_agent.weapon.key,
          f"玩家 {g.player.weapon.key} / agent {g.match.player_agent.weapon.key}")


def run():
    print("=== 3v3 新回合武器重置回归 ===")
    test_match_reset_contract()
    test_game_round_carryover_fixed()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    run()
