"""被攻击提示（屏幕中央红色环形弧）自检。

直接跑：  python3 tests/test_attack_indicator.py
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
import pygame  # noqa: E402
from match import Match  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


G = engine.build_arena(C.ARENA_TILES_X, C.ARENA_TILES_Y, C.ARENA_ROOM_W, C.ARENA_ROOM_H)


def fresh(mode: str = "match", seed: int = 7) -> Match:
    return Match(G, random.Random(seed), "normal", mode=mode)


def _enemy(m: Match):
    return [a for a in m.agents if a.team == 1][0]


def _ally_ai(m: Match):
    return [a for a in m.agents if a.team == 0 and not a.is_player][0]


# ---------------------------------------------------------------- 数据模型

def test_ping_recorded_on_player_hit():
    """玩家挨打 → 记录一条指向来源位置的提示。"""
    m = fresh()
    en = _enemy(m)
    en.x, en.y = 12.0, 4.0
    before = len(m.attack_pings)
    m.apply_damage(en, m.player_agent, False)
    check("玩家挨打后多出一条提示", len(m.attack_pings) == before + 1,
          f"{before} -> {len(m.attack_pings)}")
    p = m.attack_pings[-1]
    check("提示记录了来源坐标", abs(p[0] - 12.0) < 1e-6 and abs(p[1] - 4.0) < 1e-6,
          f"({p[0]:.1f},{p[1]:.1f})")
    check("提示初始寿命为 ATTACK_PING_LIFE", abs(p[2] - C.ATTACK_PING_LIFE) < 1e-6,
          f"{p[2]:.2f}")


def test_no_ping_when_ai_is_hit():
    """队友/敌人 AI 挨打 → 不记录被攻击提示（只关心玩家自己）。"""
    m = fresh()
    en, ally = _enemy(m), _ally_ai(m)
    en.x, en.y = 12.0, 4.0
    m.apply_damage(en, ally, False)
    check("AI 挨打不产生玩家提示", len(m.attack_pings) == 0,
          f"{len(m.attack_pings)} 条")


def test_ping_decays_and_expires():
    """提示寿命随 update 递减，过期后移除。"""
    m = fresh()
    en = _enemy(m)
    en.x, en.y = 12.0, 4.0
    m.apply_damage(en, m.player_agent, False)
    check("刚挨打有 1 条", len(m.attack_pings) == 1)
    # 推进时间超过寿命，应被清掉
    m.update(C.ATTACK_PING_LIFE + 0.1)
    check("超时后提示清零", len(m.attack_pings) == 0, f"{len(m.attack_pings)} 条")
    # 半寿命时仍在
    m.apply_damage(en, m.player_agent, False)
    m.update(C.ATTACK_PING_LIFE * 0.5)
    check("半寿命时提示仍在", len(m.attack_pings) == 1, f"{len(m.attack_pings)} 条")


def test_ping_cap():
    """同帧多次受击最多保留 6 条，列表不无限增长。"""
    m = fresh()
    en = _enemy(m)
    for i in range(10):
        en.x, en.y = float(i), 0.0
        m.apply_damage(en, m.player_agent, False)
    check("提示数量封顶 6 条", len(m.attack_pings) <= 6, f"{len(m.attack_pings)} 条")


# ---------------------------------------------------------------- HUD 绘制

class _Renderer:
    w, h = 1280, 720


class _Cam:
    x, y, yaw = 0.0, 0.0, 0.0


def test_hud_draw_runs():
    """draw_attack_indicator 在空 pings / 有 pings 时都能正常画、不报错。"""
    # 初始化一个 dummy 显示，让 pygame 的 convert/格式状态稳定，
    # 避免污染同进程里其它测试（如 test_core.test_projection 的 s.convert()）。
    pygame.init()
    pygame.display.set_mode((1, 1), pygame.SRCALPHA)
    surf = pygame.Surface((_Renderer.w, _Renderer.h), pygame.SRCALPHA)
    cam = _Cam()
    # 空列表：直接跳过
    try:
        import hud
        hud.draw_attack_indicator(surf, _Renderer(), cam, [])
        # 三个方向各放一条，验证能同时画多个且不抛异常
        pings = [[1.0, 0.0, C.ATTACK_PING_LIFE],
                 [0.0, 1.0, C.ATTACK_PING_LIFE * 0.5],
                 [-1.0, 0.0, C.ATTACK_PING_LIFE]]
        hud.draw_attack_indicator(surf, _Renderer(), cam, pings)
        ok = True
    except Exception as e:  # noqa: BLE001
        print("    exception:", repr(e))
        ok = False
    check("HUD 绘制不抛异常", ok)


def test_angle_points_right_when_attacker_on_right():
    """复刻 minimap_project 的投影，验证'屏幕右方'的攻击者对应右半弧。"""
    cam = _Cam()
    cam.yaw = 0.0
    # 玩家朝 +x（yaw=0）。把攻击者放在玩家"屏幕右方"：right 分量为正、fwd≈0。
    # 由 minimap_project：right = -dx*sin(yaw)+dy*cos(yaw) = dy（yaw=0）
    # 取 dy>0 → 右方；dx 任意小。
    dx, dy = 0.0, 5.0
    fwd = dx * math.cos(cam.yaw) + dy * math.sin(cam.yaw)
    right = -dx * math.sin(cam.yaw) + dy * math.cos(cam.yaw)
    phi = math.atan2(right, fwd)        # 0=上, 顺时针为正
    check("右侧攻击者 → 屏幕右侧弧 (phi≈+90°)", abs(phi - math.pi / 2) < 1e-6,
          f"phi={phi:.3f}")
    # 正前方（dx>0,dy=0）→ 屏幕上方 (phi≈0)
    fwd2 = 5.0 * math.cos(cam.yaw) + 0.0
    right2 = -5.0 * math.sin(cam.yaw) + 0.0
    phi2 = math.atan2(right2, fwd2)
    check("正前方攻击者 → 屏幕上弧 (phi≈0)", abs(phi2) < 1e-6, f"phi={phi2:.3f}")


def main():
    print("=== 被攻击提示（红色环形弧）回归 ===")
    test_ping_recorded_on_player_hit()
    test_no_ping_when_ai_is_hit()
    test_ping_decays_and_expires()
    test_ping_cap()
    test_hud_draw_runs()
    test_angle_points_right_when_attacker_on_right()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
