"""端到端冒烟：在真实游戏循环里按 G 扔烟、按空格跳。

单元测试管的是物理和判定，这个脚本管的是**接线**——按键有没有真的接到
动作上、烟场有没有在对战/练习之间共用、画烟会不会崩。

直接跑：  python3 tests/gameplay_smoke.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import config as C  # noqa: E402
from main import Game  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def frames(g, n: int):
    for _ in range(n):
        g.handle_events()
        g.update(1 / 60.0)
        g.draw()


def test_jump_in_game():
    g = Game()
    g.start_practice("botz")
    check("（前置）起跳前在地面", g.cam.z == 0.0 and not g.player.airborne)

    g.on_key(pygame.K_SPACE)
    check("按空格立刻进入滞空", g.player.airborne)

    peak = 0.0
    for _ in range(120):
        g.update(1 / 60.0)
        g.draw()
        peak = max(peak, g.cam.z)
    check("滞空时相机被抬高", peak > 0.12, f"peak cam.z={peak:.3f}")
    check("落地后相机复位", abs(g.cam.z) < 1e-9, f"cam.z={g.cam.z}")

    # 跳起来扫射应该更难打中（扩散惩罚）
    g.player.burst = 0
    ground_spread = g.player.spread
    g.on_key(pygame.K_SPACE)
    g.update(1 / 60.0)
    check("空中扩散被惩罚", g.player.spread > ground_spread + C.AIR_SPRAY * 0.5,
          f"{ground_spread:.5f} -> {g.player.spread:.5f}")
    for _ in range(120):
        g.update(1 / 60.0)
    check("落地后扩散恢复", abs(g.player.spread - ground_spread) < 1e-9)


def test_smoke_in_practice():
    g = Game()
    g.start_practice("botz")
    g.smoke_cd = 0.0

    left0 = g.smoke_left
    g.on_key(pygame.K_G if hasattr(pygame, "K_G") else pygame.K_g)
    check("按 G 消耗一颗烟", g.smoke_left == left0 - 1, f"{left0} -> {g.smoke_left}")
    check("场上出现一颗烟", len(g.smokes.grenades) == 1)

    # 立刻再按：应该被冷却挡下
    g.on_key(pygame.K_g)
    check("冷却期内扔不出去", len(g.smokes.grenades) == 1,
          f"{len(g.smokes.grenades)} 颗")

    expanded = False
    for _ in range(int(60 * (C.SMOKE_FUSE + C.SMOKE_GROW)) + 40):
        g.update(1 / 60.0)
        g.draw()
        if any(x.cloud_r > C.SMOKE_RADIUS * 0.9 for x in g.smokes.grenades):
            expanded = True
    check("烟在场上正常展开并渲染", expanded)

    # 烟里应该藏人：把烟种在相机脚下，靶子如果在烟里就不该被画出来
    g.smokes.clear()
    cloud = g.smokes.plant(g.cam.x + 3.0, g.cam.y, C.SMOKE_RADIUS)
    check("烟里的点判定为被藏", g.smokes.hides(cloud.cloud_x, cloud.cloud_y))

    # 上限：连续把冷却清零扔，不能超过 SMOKE_MAX_ACTIVE
    g.smokes.clear()
    thrown = 0
    for _ in range(C.SMOKE_MAX_ACTIVE + 2):
        g.smoke_cd = 0.0
        n0 = len(g.smokes.grenades)
        g.on_key(pygame.K_g)
        if len(g.smokes.grenades) > n0:
            thrown += 1
    check("练习里同时存在的烟不超上限",
          thrown <= C.SMOKE_MAX_ACTIVE, f"连续扔出 {thrown} 颗")


def test_smoke_in_match():
    g = Game()
    g.start_match()
    # 先跑两帧把 _last_round 同步上：回合切换时会清一次烟，别把要测的那颗清掉
    frames(g, 2)
    check("对战复用了同一个烟场", g.match.smokes is g.smokes)
    # 现在对战烟雾弹进经济：开局不免费配给
    check("对战开局不免费配给烟", g.smoke_left == 0, f"{g.smoke_left} 颗")

    # —— 买枪阶段按 6 花 $150 买一颗 ——
    money0 = g.match.player_money
    g.on_key(pygame.K_6)
    check("买枪阶段按 6 买到一颗烟", g.smoke_left == 1, f"{g.smoke_left} 颗")
    check("买烟扣了 $150", g.match.player_money == money0 - C.SMOKE_PRICE,
          f"${money0} -> ${g.match.player_money}")

    # 钱不够买不了
    g.match.player_money = 0
    left1 = g.smoke_left
    g.on_key(pygame.K_6)
    check("钱不够时买不了烟", g.smoke_left == left1, f"{g.smoke_left} 颗")

    # —— 烟雾弹飞行直击造成伤害（非友伤）——
    from nades import SmokeGrenade
    enemy = next(a for a in g.match.agents if a.team == 1)
    enemy.hp = 100
    enemy.alive = True
    ally = next(a for a in g.match.agents if a.team == 0 and not a.is_player)
    ally.hp = 100
    gren = SmokeGrenade(enemy.x, enemy.y, 0.3, 0.0, 0.0, 0.0, team=0)
    g.smokes.grenades.append(gren)
    g.update(1 / 60.0)            # Match.update 里会跑 _smoke_direct_hits
    check("烟雾弹直击敌人造成伤害", enemy.hp == 100 - C.SMOKE_DIRECT_DMG,
          f"敌人 hp={enemy.hp}")
    check("烟雾弹不对队友造成伤害（非友伤）", ally.hp == 100,
          f"队友 hp={ally.hp}")

    # 交火阶段扔一颗，确认不会崩且烟会走完生命周期
    g.match.state = "live"
    g.match.timer = 999.0
    g.smoke_cd = 0.0
    g.on_key(pygame.K_g)
    check("对战里能扔烟", len(g.smokes.grenades) == 2)
    check("扔完剩下的那颗就没了", g.smoke_left == 0)

    expanded = False
    for _ in range(int(60 * (C.SMOKE_FUSE + C.SMOKE_GROW)) + 40):
        g.handle_events()
        g.update(1 / 60.0)
        g.draw()
        if any(x.cloud_r > C.SMOKE_RADIUS * 0.9 for x in g.smokes.grenades):
            expanded = True
    check("对战里烟正常展开", expanded)

    # 阵亡观战时扔不了
    g.match.player_dead = True
    g.smoke_cd = 0.0
    n = len(g.smokes.grenades)
    g.on_key(pygame.K_g)
    check("阵亡观战扔不了烟", len(g.smokes.grenades) == n)


def test_no_regression_frames():
    """扔了烟 + 跳过之后，各模式再跑一段，确认渲染没被改崩。"""
    g = Game()
    g.start_practice("botz")
    g.smoke_cd = 0.0
    g.on_key(pygame.K_g)
    g.on_key(pygame.K_SPACE)
    frames(g, 240)
    check("带烟 + 跳跃连跑 240 帧不崩", True)

    colors = set()
    for x in range(0, 1280, 41):
        for y in range(0, 720, 31):
            colors.add(g.screen.get_at((x, y))[:3])
    check("画面有层次", len(colors) > 8, f"{len(colors)} 种颜色")


def test_smoke_hides_enemy_from_player():
    """玩家视线被烟挡住时，对面的人不该透出来画。

    旧逻辑：对战里 agent 根本没做烟雾遮挡检查，所以站烟一边能透过看到
    另一边的敌人。这里用一个间谍替换 hud.draw_target，统计哪些 agent 被画了。
    """
    import hud as hud_mod

    g = Game()
    g.start_match()
    frames(g, 2)  # 同步 _last_round，避免首帧被清烟逻辑干扰

    enemy = next(a for a in g.match.agents if a.team == 1 and a.alive)
    # 相机(10,10) —— 烟(20,10) —— 敌人(30,10)：烟正好挡在中间
    g.cam.x, g.cam.y = 10.0, 10.0
    enemy.x, enemy.y = 30.0, 10.0
    g.smokes.clear()
    g.smokes.plant(20.0, 10.0, radius=C.SMOKE_RADIUS)  # 满烟

    drawn = []
    orig = hud_mod.draw_target

    def spy(surf, r, cam, t, body=None, head=None, edge=None):
        drawn.append(t)

    hud_mod.draw_target = spy
    try:
        g.draw()
    finally:
        hud_mod.draw_target = orig

    check("烟挡在玩家与敌人之间时，敌人不渲染", enemy not in drawn,
          f"被画出的 agent 数={sum(1 for d in drawn if hasattr(d, 'team'))}")

    # 撤掉烟，敌人应当正常出现
    g.smokes.clear()
    drawn.clear()
    hud_mod.draw_target = spy
    try:
        g.draw()
    finally:
        hud_mod.draw_target = orig
    check("没有烟时敌人正常渲染", enemy in drawn)


def main():
    pygame.init()
    pygame.display.set_mode((1280, 720))
    print("GEOM AIM —— 烟雾弹 / 跳跃 端到端冒烟")
    print()
    print("— 跳跃 —")
    test_jump_in_game()
    print()
    print("— 练习里扔烟 —")
    test_smoke_in_practice()
    print()
    print("— 对战里扔烟 —")
    test_smoke_in_match()
    print()
    print("— 烟雾遮挡玩家视线 —")
    test_smoke_hides_enemy_from_player()
    print()
    print("— 渲染回归 —")
    test_no_regression_frames()
    print()
    print(f"通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败：")
        for f in FAIL:
            print("   -", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
