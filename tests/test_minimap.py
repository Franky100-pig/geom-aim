"""小地图自检：旋转投影 / 只显示队友 / 圆形绘制 / M 放大。

直接跑：  python3 tests/test_minimap.py
"""

from __future__ import annotations

import math
import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import config as C  # noqa: E402
import engine  # noqa: E402
import hud  # noqa: E402
from match import Match  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


G = engine.build_arena(C.MATCH_TILES_X, C.MATCH_TILES_Y, C.MATCH_ROOM_W, C.MATCH_ROOM_H)
R = engine.Renderer(640, 360, 78.0)


class FakeGame:
    def __init__(self, m, big=False):
        self.match = m
        self.gmap = G
        self.cam = engine.Camera(*(m.spawns[0] if m is not None else (14.5, 10.5)))
        self.minimap_big = big


def fresh(mode="match", seed=5):
    return Match(G, random.Random(seed), "normal", mode=mode)


# ---------------------------------------------------------------- 旋转投影

def test_project_rotation():
    """地图随视角转：正前方 → 圆心正上方；正右方 → 圆心右侧。"""
    r, scale = 60.0, 60.0 / hud.MINIMAP_VIEW
    px, py = 10.0, 10.0
    yaw = 0.0                                   # 朝 +x
    mx, my = hud.minimap_project(yaw, r, scale, r, 14.0, 10.0, px, py)
    check("正前方的点画在圆心上方", my < r and abs(mx - r) < 1e-6, f"({mx:.1f},{my:.1f})")
    mx, my = hud.minimap_project(yaw, r, scale, r, 10.0, 14.0, px, py)
    # yaw=0 时右手方向是 +y
    check("右侧的点画在圆心右边", mx > r and abs(my - r) < 1e-6, f"({mx:.1f},{my:.1f})")

    # 转身 90°：原本正前方的点应挪到侧面（水平偏移、垂直回到中线）
    mx2, my2 = hud.minimap_project(math.pi / 2, r, scale, r, 14.0, 10.0, px, py)
    check("转身 90° 后同一点移到侧面", abs(mx2 - r) > 1.0, f"({mx2:.1f},{my2:.1f})")
    check("转身 90° 后该点回到中线上", abs(my2 - r) < 1e-6, f"my={my2:.3f}")

    # 自身位置恒在圆心
    mx3, my3 = hud.minimap_project(1.234, r, scale, r, px, py, px, py)
    check("自身位置落在圆心", abs(mx3 - r) < 1e-6 and abs(my3 - r) < 1e-6)


# ---------------------------------------------------------------- 只显示队友

def test_mates_only_team():
    m = fresh()
    me = m.player_agent
    mates = hud.minimap_mates(m)
    check("自己人在列表里", any(is_self for _a, is_self in mates))
    check("不含任何敌人",
          all(a.team == me.team for a, _s in mates),
          f"队伍: {sorted({a.team for a, _s in mates})}")
    alive_team = sum(1 for a in m.agents if a.team == me.team and a.alive)
    check("数量 = 本队存活人数", len(mates) == alive_team, f"{len(mates)} vs {alive_team}")
    check("自己排在最前（最后画，不会被队友盖住）", mates[0][1] is True)


def test_mates_excludes_dead():
    m = fresh()
    me = m.player_agent
    other = [a for a in m.agents if a.team == me.team and a is not me][0]
    other.alive = False
    mates = [a for a, _s in hud.minimap_mates(m)]
    check("阵亡队友不显示", other not in mates)
    other.alive = True


# ---------------------------------------------------------------- 圆形绘制

def test_draw_no_crash():
    """3v3 与积分赛都能画出来；放大一倍也不炸。"""
    for mode in ("match", "score"):
        m = fresh(mode=mode)
        g = FakeGame(m)
        surf = engine.Renderer._surface.__func__(R, 640, 360) if False else R._surface(640, 360)
        hud.draw_minimap(surf, R, g)
        check(f"{mode} 模式小地图绘制无异常", True)
        g.minimap_big = True
        hud.draw_minimap(surf, R, g)
        check(f"{mode} 放大后绘制无异常", True)


def test_practice_no_minimap():
    """自由练习（match 为 None）不画小地图。"""
    g = FakeGame(None)
    surf = R._surface(640, 360)
    before = surf.get_at((40, 100))
    hud.draw_minimap(surf, R, g)
    check("练习模式小地图为空操作", surf.get_at((40, 100)) == before)


def test_draws_something():
    """画了东西：圆心附近的像素被改动过（背景色不是原底色）。"""
    m = fresh()
    g = FakeGame(m)
    surf = R._surface(640, 360)
    surf.fill((0, 0, 0))
    hud.draw_minimap(surf, R, g)
    r = hud.minimap_radius(g, R)
    cx, cy = int(26 * (R.h / 720.0)) + r, int(78 * (R.h / 720.0)) + r
    px = surf.get_at((cx, cy))[:3]
    check("圆心处有绘制内容", px != (0, 0, 0), f"{px}")


# ---------------------------------------------------------------- 放大

def test_zoom_doubles_radius():
    m = fresh()
    small = hud.minimap_radius(FakeGame(m), R)
    big = hud.minimap_radius(FakeGame(m, big=True), R)
    check("M 放大后半径翻倍", big == small * 2, f"{small} -> {big}")
    check("放大倍率常量为 2", hud.MINIMAP_ZOOM == 2)


def main():
    print("=== 小地图 ===")
    test_project_rotation(); print()
    test_mates_only_team(); print()
    test_mates_excludes_dead(); print()
    test_draw_no_crash(); print()
    test_practice_no_minimap(); print()
    test_draws_something(); print()
    test_zoom_doubles_radius(); print()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
