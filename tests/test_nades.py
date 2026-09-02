"""烟雾弹 + 跳跃的自检：投掷物理、封烟视线、滞空扩散惩罚。

直接跑：  python3 tests/test_nades.py
"""

from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import config as C  # noqa: E402
import nades  # noqa: E402
from engine import Camera, Renderer, build_arena  # noqa: E402
from player import Player  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


G = build_arena()


def _flat(g=None):
    """一张全空地的测试图，用来隔离物理（不掺墙）。"""
    g = g or G
    return g


# ================================================================ 投掷物理

def test_throw_flies():
    f = nades.SmokeField()
    n = f.throw(20.5, 20.5, 0.5, 1.0, 0.0)
    check("扔烟返回一个弹体", n is not None)
    if n is None:
        return
    x0 = n.x
    for _ in range(12):          # 0.2 秒
        f.update(1 / 60, G)
    check("出手后向前飞", n.x > x0 + 0.5, f"{x0:.2f} -> {n.x:.2f}")


def test_throw_lands():
    f = nades.SmokeField()
    n = f.throw(20.5, 20.5, 0.5, 1.0, 0.0)
    assert n is not None
    peak = 0.0
    for _ in range(60 * 3):
        f.update(1 / 60, G)
        peak = max(peak, n.z)
    check("出手后先上抛（有最高点）", peak > 0.55, f"peak z={peak:.2f}")
    check("最终落回地面", close(n.z, 0.0, 1e-3) and n.resting, f"z={n.z:.4f}")


def test_throw_settles_not_in_wall():
    """弹体停稳后不能卡在墙里（否则烟心在墙内，封烟判定会诡异）。"""
    f = nades.SmokeField()
    n = f.throw(20.5, 20.5, 0.5, 1.0, 0.0)
    assert n is not None
    for _ in range(60 * 4):
        f.update(1 / 60, G)
    check("停稳点不在墙里", not G.blocked(n.x, n.y, 0.12), f"({n.x:.2f},{n.y:.2f})")


# ================================================================ 烟的生命周期

def test_fuse_then_grow():
    f = nades.SmokeField()
    n = f.throw(20.5, 20.5, 0.5, 1.0, 0.0)
    assert n is not None
    steps = int(60 * (C.SMOKE_FUSE - 0.2))
    for _ in range(steps):
        f.update(1 / 60, G)
    check("引信未到不起烟", n.cloud_r == 0.0, f"r={n.cloud_r:.2f}")
    check("引信未到不挡视线", not f.blocks(10.0, 30.0, 30.0, 30.0))

    grow = int(60 * C.SMOKE_GROW) + 6
    for _ in range(grow):
        f.update(1 / 60, G)
    check("起烟后展开到接近满半径",
          n.cloud_r > C.SMOKE_RADIUS * 0.9,
          f"r={n.cloud_r:.2f} / {C.SMOKE_RADIUS}")


def test_cloud_geometry():
    """满烟时：穿心被挡、远处不被挡、烟内点被藏。"""
    f = nades.SmokeField()
    n = f.throw(20.5, 20.5, 0.5, 1.0, 0.0)
    assert n is not None
    for _ in range(int(60 * (C.SMOKE_FUSE + C.SMOKE_GROW)) + 10):
        f.update(1 / 60, G)
    cx, cy = n.cloud_x, n.cloud_y

    check("穿过烟心的视线被挡", f.blocks(cx - 10.0, cy, cx + 10.0, cy))
    check("远离烟团的视线不受影响",
          not f.blocks(cx - 10.0, cy + 30.0, cx + 10.0, cy + 30.0))
    check("烟内的点被藏住", f.hides(cx, cy))
    check("烟外的点不被藏", not f.hides(cx + C.SMOKE_RADIUS + 1.5, cy))
    check("站在烟里看不到外面", f.blocks(cx, cy, cx + 40.0, cy))


def test_cloud_expires():
    f = nades.SmokeField()
    n = f.throw(20.5, 20.5, 0.5, 1.0, 0.0)
    assert n is not None
    total = C.SMOKE_FUSE + C.SMOKE_GROW + C.SMOKE_HOLD + C.SMOKE_FADE
    for _ in range(int(60 * total) + 60):
        f.update(1 / 60, G)
    check("持续时间后烟散尽", n.done and n.cloud_r == 0.0, f"r={n.cloud_r:.2f}")
    check("散尽后不再挡视线", not f.blocks(n.cloud_x - 10.0, n.cloud_y,
                                       n.cloud_x + 10.0, n.cloud_y))


def test_max_active():
    f = nades.SmokeField()
    ok = 0
    for i in range(C.SMOKE_MAX_ACTIVE + 3):
        if f.throw(20.5 + i * 0.3, 20.5, 0.5, 1.0, 0.0) is not None:
            ok += 1
    check("同时存在的烟有上限",
          ok == C.SMOKE_MAX_ACTIVE, f"扔出 {ok} / 上限 {C.SMOKE_MAX_ACTIVE}")


def test_clear():
    f = nades.SmokeField()
    f.throw(20.5, 20.5, 0.5, 1.0, 0.0)
    f.clear()
    check("clear 之后没有烟", len(f.grenades) == 0 and not f.blocks(0, 0, 40, 40))


# ================================================================ 封烟挡 AI 视线

def test_smoke_blinds_ai():
    from ai import _visible
    from match import Match

    rng = __import__("random").Random(4242)
    m = Match(G, rng, "normal")
    a = next(x for x in m.agents if x.team == 0 and not x.is_player)
    e = next(x for x in m.agents if x.team == 1 and x.alive)

    # 先把敌人摆到有通视的地方
    ex, ey = a.x + 6.0, a.y
    if not G.clear_line(a.x, a.y, ex, ey):
        for _ in range(80):
            spot = G.random_free(rng, pad=2.0)
            if spot and G.clear_line(a.x, a.y, spot[0], spot[1]):
                ex, ey = spot
                break
    e.x, e.y = ex, ey
    check("（前置）无烟时 AI 看得见敌人", _visible(m, a, e),
          f"a=({a.x:.1f},{a.y:.1f}) e=({ex:.1f},{ey:.1f})")

    # 在两者连线中点直接种一团满烟
    mx, my = (a.x + e.x) * 0.5, (a.y + e.y) * 0.5
    m.smokes.plant(mx, my, C.SMOKE_RADIUS)
    check("烟挡在中间时 AI 看不见", not _visible(m, a, e))
    check("烟墙生效：几何上确实挡住",
          m.smokes.blocks(a.x, a.y, e.x, e.y))


# ================================================================ 跳跃

def test_jump_arc():
    p = Player()
    check("起跳前在地面", not p.airborne and close(p.z, 0.0))
    check("地面可以起跳", p.try_jump())
    peak, air = 0.0, 0.0
    for _ in range(60 * 3):
        p.update_jump(1 / 60)
        peak = max(peak, p.z)
        if p.airborne:
            air += 1 / 60
        else:
            break
    check("跳起来有高度", peak > 0.12, f"peak={peak:.3f}")
    check("落地回到地面", close(p.z, 0.0) and not p.airborne, f"z={p.z:.4f}")
    check("滞空时间在合理区间", 0.25 < air < 0.95, f"{air:.2f}s")


def test_no_double_jump():
    p = Player()
    p.try_jump()
    for _ in range(6):
        p.update_jump(1 / 60)
    check("空中不能二段跳", not p.try_jump())
    for _ in range(60 * 2):
        p.update_jump(1 / 60)
    check("落地后可以再跳", p.try_jump())


def test_air_spread_penalty():
    p = Player()
    ground = p.spread
    p.try_jump()
    for _ in range(6):
        p.update_jump(1 / 60)
    air = p.spread
    check("空中扩散明显变大", air > ground + C.AIR_SPRAY * 0.9,
          f"ground={ground:.5f} air={air:.5f}")
    for _ in range(60 * 2):
        p.update_jump(1 / 60)
    check("落地后扩散恢复", close(p.spread, ground), f"{p.spread:.5f}")


def test_jump_raises_eye():
    cam = Camera(20.5, 20.5, 0.0)
    r = Renderer(1280, 720, C.H_FOV_DEG)
    base = r.aim_height(cam, 10.0)
    cam.z = 0.3
    raised = r.aim_height(cam, 10.0)
    check("抬高相机后准星指向更高", raised > base + 0.29,
          f"{base:.3f} -> {raised:.3f}")
    check("平视时准星高度 = 眼高 + z",
          close(raised, C.EYE_HEIGHT + 0.3, 1e-6), f"{raised}")
    cam.z = 0.0
    check("落地后准星高度复原", close(r.aim_height(cam, 10.0), C.EYE_HEIGHT))


# ================================================================ 主流程

def main():
    print("GEOM AIM —— 烟雾弹 / 跳跃 自检")
    print()
    print("— 投掷物理 —")
    test_throw_flies()
    test_throw_lands()
    test_throw_settles_not_in_wall()
    print()
    print("— 烟的生命周期 —")
    test_fuse_then_grow()
    test_cloud_geometry()
    test_cloud_expires()
    test_max_active()
    test_clear()
    print()
    print("— 封烟挡视线 —")
    test_smoke_blinds_ai()
    print()
    print("— 跳跃 —")
    test_jump_arc()
    test_no_double_jump()
    test_air_spread_penalty()
    test_jump_raises_eye()
    print()
    print(f"通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败：")
        for f in FAIL:
            print("   -", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
