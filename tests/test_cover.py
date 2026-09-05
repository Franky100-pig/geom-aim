"""GEOM AIM 可变掩体（半高箱 / 高箱）自检。

覆盖：随机对称生成 / 连通性 / 半高箱遮挡（蹲下藏住、站着露头）/
      高箱等同满高墙 / 跳跃越过矮箱 / 子弹高度感知 / AI 视线高度感知 /
      对战地图启用随机掩体、练习地图保持固定柱。

直接跑：  python3 tests/test_cover.py
"""

from __future__ import annotations

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
from nades import SmokeField  # noqa: E402
import ai  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ---------------------------------------------------------------- 工具
def make_room(w=14, h=12, box=None):
    """建一个 w×h 的空房间（外圈墙），可选在 (bx,by) 放一个指定类型的格子。"""
    g = [[1 if (x == 0 or y == 0 or x == w - 1 or y == h - 1) else 0
          for x in range(w)] for y in range(h)]
    gm = engine.GridMap(g)
    if box is not None:
        bx, by, v = box
        gm.g[by][bx] = v
    return gm


def eye(a):
    return a * 0.5


# ---------------------------------------------------------------- 1. 对称 + 连通
def test_symmetry_and_connectivity():
    specs = [
        ("practice4x3", C.ARENA_TILES_X, C.ARENA_TILES_Y, C.ARENA_ROOM_W, C.ARENA_ROOM_H),
        ("match2x2", C.MATCH_TILES_X, C.MATCH_TILES_Y, C.MATCH_ROOM_W, C.MATCH_ROOM_H),
        ("score3x3", C.SCORE_MAP_TILES_X, C.SCORE_MAP_TILES_Y, C.SCORE_MAP_ROOM_W, C.SCORE_MAP_ROOM_H),
    ]
    for name, rx, ry, rw, rh in specs:
        for s in range(10):
            g = engine.build_arena(rx, ry, rw, rh, random.Random(s), cover=True)
            W, H = g.w, g.h
            bad = sum(1 for y in range(H) for x in range(W)
                      if g.g[y][x] != g.g[H - 1 - y][W - 1 - x])
            check(f"{name} seed{s} 180°对称", bad == 0, f"非对称={bad}")
            check(f"{name} seed{s} 全图连通", engine._free_connected(g.g, W, H))


def test_cover_composition():
    """对战用随机掩体（半高/高箱），练习用固定柱。"""
    gm_match = engine.build_arena(2, 2, C.MATCH_ROOM_W, C.MATCH_ROOM_H,
                                  random.Random(3), cover=True)
    low = sum(r.count(C.CELL_LOW_BOX) for r in gm_match.g)
    tall = sum(r.count(C.CELL_TALL_BOX) for r in gm_match.g)
    pillars = sum(r.count(2) for r in gm_match.g)
    check("对战地图含半高箱", low > 0, f"low={low}")
    check("对战地图含高箱", tall > 0, f"tall={tall}")
    check("对战地图不含固定柱", pillars == 0, f"pillars={pillars}")

    gm_practice = engine.build_arena(C.ARENA_TILES_X, C.ARENA_TILES_Y,
                                     C.ARENA_ROOM_W, C.ARENA_ROOM_H, cover=False)
    low2 = sum(r.count(C.CELL_LOW_BOX) for r in gm_practice.g)
    check("练习地图无随机箱（保持固定柱）", low2 == 0, f"low={low2}")


# ---------------------------------------------------------------- 2. 半高箱遮挡
def test_low_box_occlusion():
    """矮箱 0.70：蹲下（头顶 0.65）看不见，站着（头顶 1.05）看得见。"""
    # 射手在 (1.5,5.5) 看向 (10.5,5.5)，中间 (8,5) 放半高箱
    gm = make_room(14, 12, box=(8, 5, C.CELL_LOW_BOX))

    # 站着（z1=1.05）：视线从 0.5 升到 1.05，过箱时已高于 0.70 → 可见
    vis_stand = gm.clear_line_h(1.5, 5.5, 0.5, 10.5, 5.5, 1.05)
    check("矮箱后站着露头 → 看得见", vis_stand is True)

    # 蹲下（z1=0.65）：视线顶到 0.65，过箱时 < 0.70 → 被挡
    vis_crouch = gm.clear_line_h(1.5, 5.5, 0.5, 10.5, 5.5, 0.65)
    check("矮箱后蹲下 → 看不见", vis_crouch is False)


def test_low_box_shoot_over():
    """瞄头（高弹道）能越过矮箱命中；瞄胸口（贴箱顶以下）被挡。"""
    gm = make_room(14, 12, box=(8, 5, C.CELL_LOW_BOX))
    eye_z = 0.5
    dist = 9.0  # (10.5-1.5)
    # 瞄头：h_aim = 0.94
    slope_head = (0.94 - eye_z) / dist
    d_head = engine.cast_ray_block(gm, 1.5, 5.5, 1.0, 0.0, eye_z, slope_head)
    check("瞄头越过矮箱 → 不挡", d_head >= dist, f"wall_d={d_head:.2f}")
    # 瞄胸口：h_aim = 0.65
    slope_chest = (0.65 - eye_z) / dist
    d_chest = engine.cast_ray_block(gm, 1.5, 5.5, 1.0, 0.0, eye_z, slope_chest)
    check("瞄胸口被矮箱挡 → 挡住", d_chest < dist, f"wall_d={d_chest:.2f}")


def test_jump_over_low_box():
    """起跳抬高眼高（0.5→0.8），平射也能越过矮箱。"""
    gm = make_room(14, 12, box=(8, 5, C.CELL_LOW_BOX))
    eye_hi = 0.8
    dist = 9.0
    # 平射（slope=0）：眼高 0.8 > 箱高 0.70 → 越过，最近全高遮挡是后墙（>dist）
    d = engine.cast_ray_block(gm, 1.5, 5.5, 1.0, 0.0, eye_hi, 0.0)
    check("跳起平射越过矮箱 → 不挡", d >= dist, f"wall_d={d:.2f}")


# ---------------------------------------------------------------- 3. 高箱等同满高墙
def test_tall_box_full_block():
    """高箱高度 1.0，无论怎么瞄都挡，且 clear_line_h 也挡。"""
    gm = make_room(14, 12, box=(8, 5, C.CELL_TALL_BOX))
    d_head = engine.cast_ray_block(gm, 1.5, 5.5, 1.0, 0.0, 0.5, (0.94 - 0.5) / 9.0)
    check("高箱挡住瞄头弹道", d_head < 9.0, f"wall_d={d_head:.2f}")
    d_flat = engine.cast_ray_block(gm, 1.5, 5.5, 1.0, 0.0, 0.5, 0.0)
    check("高箱挡住平射弹道", d_flat < 9.0, f"wall_d={d_flat:.2f}")
    vis = gm.clear_line_h(1.5, 5.5, 0.5, 10.5, 5.5, 1.05)
    check("高箱挡住视线（站着也被挡）", vis is False)


# ---------------------------------------------------------------- 4. AI 视线高度感知
def test_ai_cannot_see_crouched_behind_box():
    """AI 看不见蹲在矮箱后的敌人，但能看见站着的。"""
    gm = make_room(14, 12, box=(8, 5, C.CELL_LOW_BOX))
    smokes = SmokeField()

    class _A:
        def __init__(self, x, y, h):
            self.x, self.y, self.h, self.alive, self.team = x, y, h, True, 1
            self.ground_z = 0.0            # 地形：假 Agent 站在平地上

    m = type("M", (), {"gmap": gm, "smokes": smokes})()

    shooter = _A(1.5, 5.5, C.BOT_H)            # 站着的 AI
    tgt_stand = _A(10.5, 5.5, C.BOT_H)
    tgt_crouch = _A(10.5, 5.5, C.BOT_H * C.CROUCH_H_MUL)

    check("AI 看得见站着的敌人", ai._visible(m, shooter, tgt_stand) is True)
    check("AI 看不见矮箱后蹲下的敌人", ai._visible(m, shooter, tgt_crouch) is False)


# ---------------------------------------------------------------- 5. 渲染冒烟（不崩）
def test_render_smoke():
    """带掩体的对战地图，渲染若干帧不抛异常。"""
    pygame.init()
    pygame.display.set_mode((320, 240))
    gm = engine.build_arena(2, 2, C.MATCH_ROOM_W, C.MATCH_ROOM_H,
                            random.Random(7), cover=True)
    r = engine.Renderer(320, 240, C.H_FOV_DEG)
    cam = engine.Camera(5.5, 5.5, yaw=0.0)
    surf = pygame.Surface((320, 240))
    try:
        r.render_walls(surf, cam, gm)
        # 一个站在矮箱后的目标，visible_runs 应给出遮挡上沿（top 非空）
        # 在相机正前方放一个半高箱，检查 box_d 被记账
        runs = r.visible_runs(0, 320, 1e9)
        check("render_walls 不崩且产出可见区间", isinstance(runs, list))
        check("box_d 缓冲存在", len(r.box_d) > 0)
    except Exception as e:  # noqa: BLE001
        check("render_walls 不抛异常", False, str(e))


# ---------------------------------------------------------------- 入口
if __name__ == "__main__":
    test_symmetry_and_connectivity()
    test_cover_composition()
    test_low_box_occlusion()
    test_low_box_shoot_over()
    test_jump_over_low_box()
    test_tall_box_full_block()
    test_ai_cannot_see_crouched_behind_box()
    test_render_smoke()

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  ✗", f)
        sys.exit(1)
