"""渲染开销基准。

跑在 dummy 驱动下，测的是纯 CPU 侧（DDA + Python 循环 + 绘图调用）。
真机显卡合成/垂直同步的开销不在这里面，所以这是**耗时下限**，
真机会比这个数略高。

用法：  python3 tests/bench.py
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import config as C  # noqa: E402
import hud  # noqa: E402
from main import Game  # noqa: E402


def bench(name: str, fn, n: int = 200) -> float:
    fn()                                   # 预热
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    ms = (time.perf_counter() - t0) / n * 1000.0
    print(f"  {name:<22s} {ms:6.3f} ms")
    return ms


def main():
    pygame.init()
    g = Game()
    g.range.set_mode("botz", g.cam)
    r, cam, surf = g.renderer, g.cam, g.screen

    print(f"\n== 渲染基准  {r.w}x{r.h}  FOV {g.hfov:.0f}°  "
          f"RENDER_COL_STEP={C.RENDER_COL_STEP} ==（dummy 驱动，CPU 侧下限）\n")

    print("分部件：")
    total = 0.0
    total += bench("天花板/地板渐变", lambda: r.draw_sky_floor(surf, cam))
    total += bench("地板网格", lambda: r.draw_floor_grid(surf, cam, g.gmap))
    total += bench("墙体光栅化", lambda: r.render_walls(surf, cam, g.gmap))

    def draw_targets():
        for t in sorted(g.range.targets,
                        key=lambda o: -((o.x - cam.x) ** 2 + (o.y - cam.y) ** 2)):
            hud.draw_target(surf, r, cam, t)

    print(f"  靶子 x{len(g.range.targets)}".ljust(24) + "  (含在整帧里)")
    total += bench("HUD + 准星 + 枪模型", lambda: (
        hud.draw_weapon(surf, r, g.player),
        hud.draw_crosshair(surf, r, g.player, 0),
        hud.draw_scoreboard(surf, r, g)))

    frame = bench("整帧 update+draw", lambda: (g.update(1 / 120.0), g.draw()))
    print(f"\n  分部件合计 ≈ {total:.3f} ms（靶子绘制未单列）")
    print(f"  整帧 {frame:.3f} ms  →  CPU 允许约 {1000.0 / frame:.0f} fps")

    print("\n不同 RENDER_COL_STEP 下的墙体开销（越小越精细）：")
    original_step = C.RENDER_COL_STEP
    for step in (1, 2, 3, 4, 6):
        C.RENDER_COL_STEP = step
        mark = "  ← 当前默认" if step == original_step else ""
        print(f"  step={step}（{r.w // step} 根射线）", end="")
        ms = bench("", lambda: r.render_walls(surf, cam, g.gmap), n=150)
        print(f"     {mark}")
    C.RENDER_COL_STEP = original_step

    print("\n结论参考：")
    print("  60 fps 的预算是 16.7 ms/帧，144 fps 是 6.9 ms/帧。")
    print("  卡就调大 config.py 里的 RENDER_COL_STEP。")


if __name__ == "__main__":
    main()
