"""地形上下起伏自检：高度场生成 / h_at 采样 / 视线遮挡 / 相机与 Agent 落地。

直接跑：  python3 tests/test_terrain.py
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

import config as C  # noqa: E402
import engine  # noqa: E402
from ai import Agent, update_agent  # noqa: E402
from match import Match  # noqa: E402
from player import Player  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


# ---------------------------------------------------------------- 生成

def test_make_heightmap():
    rng = random.Random(42)
    hm = engine.make_heightmap(60, 40, rng, 0.55, 0.16)
    check("amp>0 时返回高度场", hm is not None)
    check("尺寸 h×w", len(hm) == 40 and len(hm[0]) == 60)
    flat = all(abs(v) < 1e-9 for row in hm for v in row)
    check("不是全平", not flat)
    hi = max(abs(v) for row in hm for v in row)
    check("幅度受 amp 约束", hi <= 0.55 + 1e-9, f"max|v|={hi:.3f}")
    rng2 = random.Random(42)
    hm2 = engine.make_heightmap(60, 40, rng2, 0.55, 0.16)
    check("同种子结果一致（可复现）", hm == hm2)
    check("amp=0 返回 None", engine.make_heightmap(60, 40, random.Random(1), 0.0, 0.16) is None)


def test_build_arena_terrain():
    gm = engine.build_arena(2, 2, 12, 9, terrain_amp=0.5)
    check("build_arena 带高度图", gm.hmap is not None)
    lo = min(v for row in gm.hmap for v in row)
    hi = max(v for row in gm.hmap for v in row)
    check("高度在 [-amp, amp] 内", -0.5 - 1e-9 <= lo and hi <= 0.5 + 1e-9,
          f"[{lo:.3f}, {hi:.3f}]")
    gm2 = engine.build_arena(2, 2, 12, 9, terrain_amp=0.5)
    check("地图高度场可复现（同种子）", gm.hmap == gm2.hmap)
    gm_flat = engine.build_arena(2, 2, 12, 9, terrain_amp=0.0)
    check("amp=0 时无高度图", gm_flat.hmap is None)


# ---------------------------------------------------------------- 采样

def _flat_grid(w=20, h=20):
    return [[0] * w for _ in range(h)]


def test_h_at_flat_map():
    gm = engine.GridMap(_flat_grid())
    check("无高度图 h_at 恒为 0",
          gm.h_at(3.7, 9.2) == 0.0 and gm.h_at(0.0, 0.0) == 0.0)


def test_h_at_bilinear():
    hm = [[0.0] * 20 for _ in range(20)]
    hm[5][5] = 1.0                       # 只有格 (5,5) 高 1.0
    gm = engine.GridMap(_flat_grid(), hmap=hm)
    check("格中心取到原值", abs(gm.h_at(5.5, 5.5) - 1.0) < 1e-9)
    mid = gm.h_at(6.0, 5.5)              # (5,5) 与 (6,5) 之间 → 0.5
    check("向邻格线性过渡", abs(mid - 0.5) < 1e-9, f"{mid:.3f}")
    far = gm.h_at(15.5, 15.5)
    check("远处不受影响", far == 0.0, f"{far:.3f}")
    out = gm.h_at(-5.0, -5.0)
    check("越界夹到边缘不炸", isinstance(out, float))


# ---------------------------------------------------------------- 视线遮挡

def _ridge_map():
    """中间一道南北向山脊（高 0.9），两边平地。"""
    w, h = 24, 12
    g = [[0] * w for _ in range(h)]
    hm = [[0.0] * w for _ in range(h)]
    for y in range(h):
        hm[y][12] = 0.9
        hm[y][11] = 0.45
        hm[y][13] = 0.45
    return engine.GridMap(g, hmap=hm)


def test_terrain_blocks_sight():
    gm = _ridge_map()
    # 蹲在平地上（眼高 0.35）看山脊对面平地上躺着的低目标（顶 0.3）：
    # 视线中途高度 < 0.9 → 被山脊挡住
    vis = gm.clear_line_h(2.5, 5.5, 0.35, 20.5, 5.5, 0.3)
    check("低视线被山脊挡住", vis is False)
    # 站在高台上看：两端都抬到 1.2 → 视线越过 0.9 山脊
    vis2 = gm.clear_line_h(2.5, 5.5, 1.2, 20.5, 5.5, 1.3)
    check("高视线越过山脊", vis2 is True, f"vis2={vis2}")
    # 纯地形遮挡判定同样成立
    check("terrain_occludes 同样挡低视线",
          gm.terrain_occludes(2.5, 5.5, 0.35, 20.5, 5.5, 0.3) is True)
    check("terrain_occludes 不挡高视线",
          gm.terrain_occludes(2.5, 5.5, 1.2, 20.5, 5.5, 1.3) is False)


def test_flat_map_sight_unchanged():
    """平整地图（hmap=None）视线判定与旧版一致：山脊逻辑完全不参与。"""
    gm = engine.GridMap(_flat_grid(30, 12))
    vis = gm.clear_line_h(2.5, 5.5, 0.35, 26.5, 5.5, 0.3)
    check("平地低视线畅通（无地形可挡）", vis is True)
    check("terrain_occludes 平地恒 False",
          gm.terrain_occludes(2.5, 5.5, 0.35, 26.5, 5.5, 0.3) is False)


# ---------------------------------------------------------------- 落地

def test_player_ground_follow():
    hm = [[0.0] * 20 for _ in range(20)]
    for y in range(20):
        hm[y][10] = 0.8
    gm = engine.GridMap(_flat_grid(), hmap=hm)
    p = Player()
    cam = engine.Camera(10.5, 5.5)

    class FakeKeys(dict):
        def __missing__(self, k):
            return 0

    keys = FakeKeys()
    p.update_move(0.016, cam, gm, keys)
    check("玩家脚下高度 = 地形高度", abs(p.ground_z - 0.8) < 1e-6,
          f"{p.ground_z:.3f}")
    # 走回平地 → 高度回落
    cam.x, cam.y = 4.5, 5.5
    p.update_move(0.016, cam, gm, keys)
    check("走回平地高度回落", abs(p.ground_z) < 1e-6, f"{p.ground_z:.3f}")


def test_agent_ground_follow():
    gm = engine.build_arena(2, 2, 12, 9, terrain_amp=0.0)   # 先要 arena 属性
    hm = [[0.0] * gm.w for _ in range(gm.h)]
    for y in range(gm.h):
        hm[y][15] = 0.6
    gm.hmap = hm
    m = Match(gm, random.Random(3), "normal")
    m.state = "live"
    m.live_t = 99.0
    a = [x for x in m.agents if x.team == 1][0]
    a.x, a.y = 15.5, 15.5
    rng = random.Random(1)
    tune = dict(C.AI_PRESETS["normal"])
    update_agent(m, a, 1 / 60, rng, tune)
    check("AI 脚下高度 = 地形高度", abs(a.ground_z - 0.6) < 1e-6,
          f"{a.ground_z:.3f}")


# ---------------------------------------------------------------- 渲染冒烟

def test_render_smoke():
    """带地形的地图完整渲染一帧不炸（墙/地面网格/精灵都过一遍）。"""
    gm = engine.build_arena(2, 2, 12, 9, cover=True, terrain_amp=0.55)
    m = Match(gm, random.Random(5), "normal")
    m.state = "live"
    r = engine.Renderer(320, 200, 78.0)
    cam = engine.Camera(*gm.h_at_free_spawn(m) if hasattr(gm, "h_at_free_spawn")
                        else m.spawns[0])
    cam.x, cam.y = m.spawns[0]
    # 画一帧：背景 + 地面网格 + 墙 + 一个 agent 精灵
    surf = r._surface(320, 200)
    r.draw_sky_floor(surf, cam)
    r.draw_floor_grid(surf, cam, gm)
    r.render_walls(surf, cam, gm)
    for a in m.agents[:3]:
        a.x, a.y = cam.x + 5.0, cam.y + 2.0
        a.ground_z = gm.h_at(a.x, a.y)
        geom = r.sprite_geom(cam, a.x, a.y, a.h, a.w, a.ground_z)
        if geom is not None:
            cx, yb, hpx, wpx, depth = geom
            check(f"精灵踩在地形上 depth={depth:.1f}",
                  hpx > 0 and wpx > 0 and depth > 0.3)
            break
    check("带地形渲染一帧无异常", True)


def main():
    print("=== 地形上下起伏 ===")
    test_make_heightmap(); print()
    test_build_arena_terrain(); print()
    test_h_at_flat_map(); print()
    test_h_at_bilinear(); print()
    test_terrain_blocks_sight(); print()
    test_flat_map_sight_unchanged(); print()
    test_player_ground_follow(); print()
    test_agent_ground_follow(); print()
    test_render_smoke(); print()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
