"""回归测试：两个 3v3 手感 Bug。

Bug 1：弹匣打空后卡在"换弹中"开不了火 —— 根因是单机玩家（local）的 reload_t
       在主循环里从没被 tick_reload 推进，只有 AI / 联网真人有。
Bug 2：用狙击（开镜）后切回步枪，移动速度被开镜减速一直拖慢 —— 根因是移动公式
       只要 self.ads 为真就减速，不看当前武器是不是真能放大（zoom>1）的狙击系。

直接跑：  python3 tests/test_reload_move_bugs.py
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
import engine  # noqa: E402
import main  # noqa: E402
from ai import ammo_of, start_reload  # noqa: E402
from weapons import MATCH_WEAPONS  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def _press(w: bool = False, a: bool = False, s: bool = False, d: bool = False):
    keys = [0] * 512
    if w:
        keys[pygame.K_w] = 1
    if a:
        keys[pygame.K_a] = 1
    if s:
        keys[pygame.K_s] = 1
    if d:
        keys[pygame.K_d] = 1
    return keys


def _reach_speed(weapon, ads, frames: int = 25):
    """让速度达到稳态（避免单帧加速未到顶 + 撞墙清零），返回末速度大小。

    每帧把相机放回一个无障碍点，这样碰撞永远不触发、只测速度公式本身。
    """
    pl = main.Player()
    pl.weapon = weapon
    pl.ads = ads
    gmap = engine.build_arena(C.ARENA_TILES_X, C.ARENA_TILES_Y,
                              C.ARENA_ROOM_W, C.ARENA_ROOM_H)
    cam = engine.Camera(5.5, 5.5)
    fx, fy = gmap.center_free()
    for _ in range(frames):
        cam.x, cam.y = fx, fy
        pl.update_move(1 / 60, cam, gmap, _press(w=True))
    return math_hypot(pl.vx, pl.vy)


# ---------------------------------------------------------------- Bug 1

def test_local_player_reload_ticks():
    """单机玩家的换弹必须走完：reload_t 归零、弹匣补满（不再卡死）。"""
    g = main.Game()
    g.start_match()
    m = g.match
    pa = m.player_agent

    # 换弹逻辑是"枪"专属，测试显式给一把有弹匣的手枪（默认已是近战刀 mag=0）。
    pa.weapon = MATCH_WEAPONS["pistol"]
    pa.mags = {"pistol": MATCH_WEAPONS["pistol"].mag}

    # 清掉敌人，避免 AI 在测试窗口内打死玩家（死了就不走 tick_reload 分支）。
    # 这里只验证"换弹计时被推进"这一条，胜负逻辑不是本测试对象。
    m.agents = [pa]

    # 模拟"弹匣打空 → 触发换弹"，把 reload_t 顶到满值
    pa.mags[pa.weapon.key] = 0
    assert start_reload(pa), "空仓应能开始换弹"
    check("换弹已触发 reload_t 到位", abs(pa.reload_t - C.RELOAD_TIME) < 1e-6,
          f"{pa.reload_t:.2f}")

    # 跑满换弹时长（经真实主循环 _update_match → tick_reload）
    frames = int((C.RELOAD_TIME + 0.2) * 60)
    for _ in range(frames):
        g.update(1 / 60)

    check("经主循环后 reload_t 归零（不再卡死）", pa.reload_t == 0.0,
          f"{pa.reload_t:.3f}")
    check("经主循环后弹匣补满", ammo_of(pa) == pa.weapon.mag,
          f"{ammo_of(pa)} / {pa.weapon.mag}")


def test_empty_triggers_reload_then_recovers():
    """端到端：打空 → 自动换弹 → 走完 → 又能开火（复刻玩家体感）。"""
    g = main.Game()
    g.start_match()
    m = g.match
    pa = m.player_agent

    # 换弹逻辑是"枪"专属，测试显式给一把有弹匣的手枪（默认已是近战刀 mag=0）。
    pa.weapon = MATCH_WEAPONS["pistol"]
    pa.mags = {"pistol": MATCH_WEAPONS["pistol"].mag}

    m.agents = [pa]

    pa.mags[pa.weapon.key] = 0
    # 触发自动换弹的入口：_match_can_shoot 空仓会 start_reload
    assert not g._match_can_shoot(), "空仓时不应允许开火"
    check("空仓自动起换弹", pa.reload_t > 0, f"{pa.reload_t:.2f}")

    for _ in range(int((C.RELOAD_TIME + 0.2) * 60)):
        g.update(1 / 60)

    check("换弹后 _match_can_shoot 恢复", g._match_can_shoot())
    check("换弹后弹匣满", ammo_of(pa) == pa.weapon.mag, f"{ammo_of(pa)}")


# ---------------------------------------------------------------- Bug 2

def test_sniper_to_rifle_no_slowdown():
    """从狙击（开镜）切回步枪，即使 ads 仍残留为真，移动也不该被减速。"""
    # —— 情景一：手持步枪，但 ads 被误留为真（切枪未退镜）——
    rifle_speed = _reach_speed(MATCH_WEAPONS["rifle"], ads=True)

    # —— 情景二：手持 AWP 且真开镜（应当减速）——
    awp_speed = _reach_speed(MATCH_WEAPONS["awp"], ads=True)

    check("步枪（ads 残留）按全速移动", rifle_speed > C.MOVE_SPEED * 0.9,
          f"{rifle_speed:.2f} vs {C.MOVE_SPEED:.2f}")
    check("AWP 开镜按减速移动", awp_speed < C.MOVE_SPEED * 0.7,
          f"{awp_speed:.2f} vs {C.MOVE_SPEED * C.SNIPER_MOVE_MUL:.2f}")
    check("步枪明显快于 AWP 开镜", rifle_speed > awp_speed * 1.5,
          f"{rifle_speed:.2f} vs {awp_speed:.2f}")


def test_move_slowdown_only_for_scoping_weapons():
    """移动减速只对 zoom>1 的武器生效；zoom=1 的枪（步枪/冲锋枪）永不减速。"""
    for key in ("pistol", "smg", "rifle", "dmr", "awp"):
        sp = _reach_speed(MATCH_WEAPONS[key], ads=True)   # 全部"开镜"
        if MATCH_WEAPONS[key].zoom > 1.0:
            check(f"{key}(zoom>1) 开镜减速", sp < C.MOVE_SPEED * 0.7, f"{sp:.2f}")
        else:
            check(f"{key}(zoom=1) 不减速", sp > C.MOVE_SPEED * 0.9, f"{sp:.2f}")


def math_hypot(x, y):
    return (x * x + y * y) ** 0.5


def run_tests():
    print("=== 换弹卡死 + 狙击切步枪减速 回归 ===")
    test_local_player_reload_ticks(); print()
    test_empty_triggers_reload_then_recovers(); print()
    test_sniper_to_rifle_no_slowdown(); print()
    test_move_slowdown_only_for_scoping_weapons(); print()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
