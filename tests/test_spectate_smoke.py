"""GEOM AIM 阵亡观战 & AI 用烟节制 自检。

观战：阵亡后先原地倒地，DEATH_CAM_HOLD 秒后切到队友第一视角；
      整个过程中鼠标一律不参与（以前一动鼠标画面就甩）。
AI 烟：过闸（冷静期 / 队伍配额 / 自身在烟里）→ 场景判定 → 随机延迟 → 概率出手。

直接跑：  python3 tests/test_spectate_smoke.py
"""

from __future__ import annotations

import contextlib
import math
import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import ai as AI  # noqa: E402
import config as C  # noqa: E402
import engine  # noqa: E402
import main as M  # noqa: E402
from match import Match  # noqa: E402

PASS, FAIL = [], []

DT = 1 / 60.0


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


# 3v3 回合制地图
G = engine.build_arena(C.MATCH_TILES_X, C.MATCH_TILES_Y,
                       C.MATCH_ROOM_W, C.MATCH_ROOM_H)


@contextlib.contextmanager
def visible_stub():
    """把 AI 的视线判定打桩成"永远看得见"，用来隔离测试投烟的场景逻辑。

    否则能不能扔取决于地图几何，测试就变成随机成败了。
    """
    old = AI._visible
    AI._visible = lambda m, a, e: True
    try:
        yield
    finally:
        AI._visible = old


@contextlib.contextmanager
def chance(value: float):
    old = C.SMOKE_AI_CHANCE
    C.SMOKE_AI_CHANCE = value
    try:
        yield
    finally:
        C.SMOKE_AI_CHANCE = old


# ================================================================ 观战镜头

def _dead_game():
    """造一个「玩家已阵亡」的 3v3 对局，且已跳过买枪阶段进 live。"""
    g = M.Game()
    g.start_match()
    m = g.match
    m.state = "live"
    m.timer = 999.0
    g.update(0.05)              # 让 _last_round 同步、镜头摆到我方出生点
    m.player_dead = True
    m.player_hp = 0
    return g, m


def test_death_fall_phase():
    g, m = _dead_game()
    x0, y0 = g.cam.x, g.cam.y

    # 跑满倒地动画，但还没到切视角的时间
    steps = int(0.55 / DT)
    for _ in range(steps):
        g.update(DT)

    check("倒地阶段尚未切换视角", g.death_t < C.DEATH_CAM_HOLD,
          f"death_t={g.death_t:.2f}")
    check("倒地阶段镜头留在死亡点",
          math.hypot(g.cam.x - x0, g.cam.y - y0) < 1e-9)
    check("眼高已落到地面附近",
          close(g.cam.z, C.DEATH_EYE_H - C.EYE_HEIGHT, 0.02),
          f"z={g.cam.z:.3f}")
    check("倒地时视线被压低", g.cam.eff_pitch_px < 0.0,
          f"pitch={g.cam.eff_pitch_px:.1f}")


def test_switch_to_teammate():
    g, m = _dead_game()
    for _ in range(int((C.DEATH_CAM_HOLD + 0.40) / DT)):
        g.update(DT)

    spec = m.spectate_target()
    if spec is None:
        check("观战阶段能找到活着的队友", False)
        return

    check("已切到队友视角（位置贴合）",
          math.hypot(g.cam.x - spec.x, g.cam.y - spec.y) < 1e-9)
    check("已切到队友视角（朝向贴合）", close(g.cam.eff_yaw, spec.yaw, 1e-9),
          f"cam={g.cam.eff_yaw:.4f} mate={spec.yaw:.4f}")
    check("观战时俯仰归零", close(g.cam.eff_pitch_px, 0.0, 1e-9))
    check("观战时眼高归零", close(g.cam.z, 0.0, 1e-9))
    check("观战时朝向基准值与生效值一致",
          close(g.cam.yaw, g.cam.eff_yaw, 1e-12))


def test_mouse_locked_while_spectating():
    g, m = _dead_game()
    for _ in range(int((C.DEATH_CAM_HOLD + 0.40) / DT)):
        g.update(DT)

    y0, p0 = g.cam.eff_yaw, g.cam.eff_pitch_px
    for _ in range(40):                 # 疯狂晃鼠标
        g.look(80, 60)

    check("观战时鼠标不改朝向", close(g.cam.eff_yaw, y0, 1e-12),
          f"{y0:.6f} -> {g.cam.eff_yaw:.6f}")
    check("观战时鼠标不改俯仰", close(g.cam.eff_pitch_px, p0, 1e-12),
          f"{p0:.6f} -> {g.cam.eff_pitch_px:.6f}")


def test_mouse_locked_during_fall():
    g, m = _dead_game()
    g.update(DT)
    y0, p0 = g.cam.eff_yaw, g.cam.eff_pitch_px
    for _ in range(20):
        g.look(50, -40)
    check("倒地阶段鼠标同样不参与", close(g.cam.eff_yaw, y0, 1e-12)
          and close(g.cam.eff_pitch_px, p0, 1e-12))


def test_switch_smoothing():
    g, m = _dead_game()
    for _ in range(int((C.DEATH_CAM_HOLD + 0.40) / DT)):
        g.update(DT)

    first = m.spectate_target()
    if first is None:
        check("换人插值：有可观的队友", False)
        return
    first.alive = False                  # 干掉当前观战目标，迫使换人
    g.update(DT)
    second = m.spectate_target()
    if second is None or second is first:
        check("换人插值：能切到另一个队友", False)
        return

    check("换人瞬间不硬跳到新朝向",
          abs(g.cam.yaw - second.yaw) > 1e-9,
          f"cam={g.cam.yaw:.4f} new={second.yaw:.4f}")
    for _ in range(int(C.SPEC_SWITCH_TIME / DT) + 6):
        g.update(DT)
    check("插值结束后对齐新队友朝向",
          close(g.cam.eff_yaw, second.yaw, 1e-6),
          f"cam={g.cam.eff_yaw:.4f} mate={second.yaw:.4f}")


def test_respawn_resets_death_cam():
    g = M.Game()
    g.start_score()
    m = g.match
    # 伪造阵亡必须把重生计时一起设上，否则 _update_score 下一帧就把人拉起来了
    m.player_dead = True
    m.player_hp = 0
    m.player_agent.alive = False
    m.player_agent.respawn_timer = C.SCORE_RESPAWN_DELAY
    m.player_respawn = C.SCORE_RESPAWN_DELAY

    for _ in range(10):
        g.update(DT)
    check("积分赛阵亡后进入倒地计时", g.death_t > 0.0, f"death_t={g.death_t:.3f}")
    check("倒地期间还没重生", m.player_dead)

    for _ in range(int(4.0 / DT)):
        g.update(DT)
        if not m.player_dead:
            break
    check("重生后倒地计时归零", close(g.death_t, 0.0, 1e-9))
    check("重生后清空观战目标", g._spec_agent is None)


# ================================================================ AI 用烟

def _mk(seed=3):
    rng = random.Random(seed)
    m = Match(G, rng, "normal")
    m.state = "live"
    m.timer = 999.0
    m.live_t = C.SMOKE_AI_CALM + 1.0      # 默认已过冷静期
    m.smokes.clear()
    return m, rng


def _ally(m):
    return next(x for x in m.agents if x.team == 0 and not x.is_player)


def _foe(m):
    return next(x for x in m.agents if x.team == 1 and x.alive)


def _arm(a, e, dist):
    """把敌人摆到 a 正东 dist 格处，并给 a 装满烟。"""
    e.x, e.y = a.x + dist, a.y
    a.target = e
    a.smoke_charges = 2
    a.smoke_cd = 0.0
    a.smoke_intent = 0.0
    a.smoke_aim = None


def test_calm_period_blocks():
    m, rng = _mk()
    m.live_t = 0.0                       # 交火刚开始
    a, e = _ally(m), _foe(m)
    _arm(a, e, 20.0)
    with visible_stub(), chance(1.0):
        for _ in range(int(3.0 / DT)):
            AI.ai_maybe_throw_smoke(m, a, rng, DT)
    check("开局冷静期内一颗都不扔", len(m.smokes.grenades) == 0,
          f"live_t={m.live_t:.1f}")


def test_close_range_never_throws():
    m, rng = _mk()
    a, e = _ally(m), _foe(m)
    _arm(a, e, 6.0)                      # 远小于 SMOKE_AI_MIN_DIST
    with visible_stub(), chance(1.0):
        for _ in range(int(5.0 / DT)):
            AI.ai_maybe_throw_smoke(m, a, rng, DT)
    check("近距离交火不扔烟（不糊自己的视线）", len(m.smokes.grenades) == 0)
    check("近距离连投掷意图都不起", a.smoke_intent == 0.0)


def test_long_range_throws_after_delay():
    m, rng = _mk()
    a, e = _ally(m), _foe(m)
    _arm(a, e, 20.0)
    with visible_stub(), chance(1.0):
        AI.ai_maybe_throw_smoke(m, a, rng, DT)
        check("中远距离判定通过先起延迟、不当场扔",
              len(m.smokes.grenades) == 0 and a.smoke_intent > 0.0,
              f"intent={a.smoke_intent:.2f}")
        for _ in range(300):
            AI.ai_maybe_throw_smoke(m, a, rng, DT)
            if m.smokes.grenades:
                break
    check("延迟走完后才真的扔出去", len(m.smokes.grenades) == 1)
    check("扔完携带量递减", a.smoke_charges == 1, f"charges={a.smoke_charges}")
    check("扔完意图已清空", a.smoke_intent == 0.0 and a.smoke_aim is None)


def test_probability_gate():
    m, rng = _mk()
    a, e = _ally(m), _foe(m)
    _arm(a, e, 20.0)
    # 意图解算后会立刻起新意图，所以不能断言它恒为 0；
    # 要验的是「解算后不卡死」，即能反复走完延迟周期。
    cycles, prev = 0, 0.0
    with visible_stub(), chance(0.0):    # 概率闸门关死
        for _ in range(int(8.0 / DT)):
            AI.ai_maybe_throw_smoke(m, a, rng, DT)
            if a.smoke_intent > 0.0 and prev <= 0.0:
                cycles += 1
            prev = a.smoke_intent
    check("概率为 0 时延迟走完也不出手", len(m.smokes.grenades) == 0)
    check("概率为 0 时意图能正常复位（不卡死）", cycles >= 2, f"cycles={cycles}")


def test_team_quota():
    m, rng = _mk()
    a, e = _ally(m), _foe(m)
    _arm(a, e, 20.0)
    m.smokes.plant(a.x + 6.0, a.y, C.SMOKE_RADIUS)   # 本队（team 0）已在场一团
    with visible_stub(), chance(1.0):
        for _ in range(int(5.0 / DT)):
            AI.ai_maybe_throw_smoke(m, a, rng, DT)
    check("本队已有烟在场上就不再扔", len(m.smokes.grenades) == 1,
          f"场上 {len(m.smokes.grenades)} 团")


def test_no_throw_while_inside_smoke():
    m, rng = _mk()
    a, e = _ally(m), _foe(m)
    _arm(a, e, 20.0)
    g = m.smokes.plant(a.x, a.y, C.SMOKE_RADIUS)
    g.team = 1                            # 归到敌方名下，隔离「身处烟中」这一条
    with visible_stub(), chance(1.0):
        for _ in range(int(5.0 / DT)):
            AI.ai_maybe_throw_smoke(m, a, rng, DT)
    check("自己站在烟里时不扔", len(m.smokes.grenades) == 1,
          f"场上 {len(m.smokes.grenades)} 团（应只剩 planted 那团）")


def test_advance_smoke_is_per_second():
    """推进掩护烟按 dt 计概率，不再按帧（旧实现 10 秒会触发上百次）。"""
    m, rng = _mk()
    a = _ally(m)
    a.target = None
    a.path = [(int(a.x) + 3, int(a.y))]
    a.smoke_charges = 2
    a.smoke_cd = 0.0
    a.smoke_intent = 0.0

    triggers, prev = 0, 0.0
    with visible_stub(), chance(0.0):     # 不出手，免得冷却干扰计数
        for _ in range(int(10.0 / DT)):
            AI.ai_maybe_throw_smoke(m, a, rng, DT)
            if a.smoke_intent > 0.0 and prev <= 0.0:
                triggers += 1
            prev = a.smoke_intent

    expect = C.SMOKE_AI_ADV_RATE * 10.0   # 10 秒的期望触发次数
    check("推进掩护烟按秒计，10 秒内触发次数很低", triggers <= 3,
          f"triggers={triggers}，期望约 {expect:.2f}")


def main():
    test_death_fall_phase(); print()
    test_switch_to_teammate(); print()
    test_mouse_locked_while_spectating(); print()
    test_mouse_locked_during_fall(); print()
    test_switch_smoothing(); print()
    test_respawn_resets_death_cam(); print()
    test_calm_period_blocks(); print()
    test_close_range_never_throws(); print()
    test_long_range_throws_after_delay(); print()
    test_probability_gate(); print()
    test_team_quota(); print()
    test_no_throw_while_inside_smoke(); print()
    test_advance_smoke_is_per_second(); print()

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for n in FAIL:
            print("   FAIL:", n)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
