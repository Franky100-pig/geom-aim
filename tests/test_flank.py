"""AI 战术自检：偷背身（背身检测 + 绕后包抄 + 背身时贴身接近）。

直接跑：  python3 tests/test_flank.py
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
from ai import Agent, back_exposed, flank_point, update_agent  # noqa: E402
from match import Match  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


# 用真实竞技场（带 room_w/tiles_x 等属性，Match 要用），但把内部所有墙清成
# 空地、只留最外圈边界——这样视线永远不会被挡，能稳定复现"目标可见时 AI 的
# 战术决策"，不被真实地图里"绕墙丢失视线"干扰。包抄点落点测试依旧有效（开放
# 地图上 flank_point 总能落到空地）。
G = engine.build_arena(C.ARENA_TILES_X, C.ARENA_TILES_Y, C.ARENA_ROOM_W, C.ARENA_ROOM_H)
for _y in range(1, G.h - 1):
    for _x in range(1, G.w - 1):
        G.g[_y][_x] = 0


def find_pair(dist_lo=6.0, dist_hi=12.0):
    """找一对有视线、距离适中的空地点。"""
    rng = random.Random(11)
    for _ in range(4000):
        ax, ay = G.random_free(rng, pad=2.0)
        bx, by = G.random_free(rng, pad=2.0)
        d = math.hypot(bx - ax, by - ay)
        if dist_lo <= d <= dist_hi and G.clear_line(ax, ay, bx, by):
            return (ax, ay), (bx, by)
    raise RuntimeError("没找到合适的测试点")


# ---------------------------------------------------------------- 背身检测

def test_back_exposed():
    """目标背对我 → True；正面对着我 → False。"""
    me = (0.0, 0.0)
    # 目标在 (10, 0)，朝向 +x（背对原点方向的我）
    tgt_away = type("T", (), dict(x=10.0, y=0.0, yaw=0.0))()
    check("目标背对我 → 背身暴露", back_exposed(tgt_away, me[0], me[1]) is True)

    tgt_face = type("T", (), dict(x=10.0, y=0.0, yaw=math.pi))()
    check("目标正面对我 → 不暴露", back_exposed(tgt_face, me[0], me[1]) is False)

    tgt_side = type("T", (), dict(x=10.0, y=0.0, yaw=math.pi / 2))()
    check("目标侧向对我 → 不算背身", back_exposed(tgt_side, me[0], me[1]) is False)


# ---------------------------------------------------------------- 包抄点

def test_flank_point_behind():
    rng = random.Random(3)
    tgt = type("T", (), dict(x=20.0, y=20.0, yaw=0.0))()   # 朝 +x
    pt = flank_point(G, tgt, rng)
    check("能算出包抄点", pt is not None, f"{pt}")
    if pt:
        # 包抄点应落在目标"身后"：从目标指向包抄点的向量与目标朝向夹角 > 90°
        dx, dy = pt[0] - tgt.x, pt[1] - tgt.y
        dot = math.cos(tgt.yaw) * dx + math.sin(tgt.yaw) * dy
        check("包抄点在目标身后", dot < 0, f"dot={dot:.2f}")
        d = math.hypot(dx, dy)
        check("包抄点距离合理（不贴脸也不太远）",
              2.0 <= d <= C.AI_FLANK_RADIUS + 3.0, f"d={d:.2f}")
        check("包抄点没落在墙里", not G.blocked(pt[0], pt[1], 0.35))


def test_flank_point_avoids_walls():
    """目标贴墙时包抄点也要落在可站位置（或干脆放弃）。"""
    rng = random.Random(5)
    for i in range(30):
        x, y = G.random_free(rng, pad=2.0)
        tgt = type("T", (), dict(x=x, y=y, yaw=rng.uniform(0, math.tau)))
        pt = flank_point(G, tgt, rng)
        if pt is not None:
            assert not G.blocked(pt[0], pt[1], 0.35), f"包抄点落在墙里 {pt}"
    check("30 次采样包抄点都可站立", True)


# ---------------------------------------------------------------- 战术触发

def keep_alive(m, tgt):
    """测试期间不让目标被打死，否则 AI 会退出交火状态、永远等不到战术触发。"""
    tgt.hp = C.AGENT_HP
    m.player_hp = C.PLAYER_HP


def _setup(seed=7, diff="expert"):
    m = Match(G, random.Random(seed), diff)
    m.state = "live"
    m.live_t = 99.0          # 跳过 AI 用烟的开局冷静期
    (ax, ay), (bx, by) = find_pair()
    a = [x for x in m.agents if x.team == 1][0]      # 敌人（我们观察它）
    a.x, a.y = ax, ay
    tgt = m.player_agent                              # 目标是玩家影子
    tgt.x, tgt.y = bx, by
    tgt.alive = True
    # 让目标背对着 a：朝向远离 a 的方向
    tgt.yaw = math.atan2(tgt.y - a.y, tgt.x - a.x)
    a.yaw = math.atan2(tgt.y - a.y, tgt.x - a.x)
    return m, a, tgt


def test_flank_triggers():
    """目标正面朝我（压上去会被打）→ 高难度 AI 迟早会起意绕后包抄。"""
    m, a, tgt = _setup()
    rng = random.Random(7)
    tune = dict(C.AI_PRESETS["expert"])
    got = False
    for _ in range(600):                # 10 秒
        tgt.yaw = math.atan2(a.y - tgt.y, a.x - tgt.x)   # 一直正面盯着 AI
        keep_alive(m, tgt)
        update_agent(m, a, 1 / 60, rng, tune)
        if a.flank_goal is not None:
            got = True
            break
    check("目标正面朝我时会绕后包抄", got is True, f"flank_goal={a.flank_goal}")


def test_back_exposed_prefers_push_over_flank():
    """目标把背露给我时，正确解是悄悄压上去偷，而不是绕远路。

    （绕后留给"目标正面盯着我、压不上去"的情况，见 test_flank_triggers。）
    """
    m, a, tgt = _setup()
    rng = random.Random(7)
    tune = dict(C.AI_PRESETS["expert"])
    for _ in range(600):
        tgt.yaw = math.atan2(tgt.y - a.y, tgt.x - a.x)   # 一直保持背身
        keep_alive(m, tgt)
        update_agent(m, a, 1 / 60, rng, tune)
        if math.hypot(tgt.x - a.x, tgt.y - a.y) < C.AI_FLANK_MIN_DIST:
            break
    check("背身时选择压近而不是绕后", a.flank_goal is None, f"flank_goal={a.flank_goal}")
    check("已经压到近距离",
          math.hypot(tgt.x - a.x, tgt.y - a.y) < C.AI_FLANK_MIN_DIST + 1.0,
          f"d={math.hypot(tgt.x - a.x, tgt.y - a.y):.2f}")


def test_flank_cleared_on_low_hp():
    """血量见底就不绕后了，先保命。"""
    m, a, tgt = _setup()
    rng = random.Random(7)
    tune = dict(C.AI_PRESETS["expert"])
    a.flank_goal = (a.x + 2.0, a.y)
    a.hp = C.AI_FLANK_HP_MIN - 1
    update_agent(m, a, 1 / 60, rng, tune)
    check("低血取消包抄", a.flank_goal is None)


def test_flank_cleared_on_timeout():
    m, a, tgt = _setup()
    rng = random.Random(7)
    tune = dict(C.AI_PRESETS["expert"])
    a.flank_goal = (a.x + 3.0, a.y + 3.0)
    a.flank_t = C.AI_FLANK_MAX_T + 0.1
    update_agent(m, a, 1 / 60, rng, tune)
    check("超时取消包抄", a.flank_goal is None)


def test_flank_cleared_when_target_lost():
    m, a, tgt = _setup()
    rng = random.Random(7)
    tune = dict(C.AI_PRESETS["expert"])
    a.flank_goal = (a.x + 3.0, a.y)
    # 让所有敌人（含玩家影子）全部阵亡 → AI 彻底失去可见目标
    for e in m.agents:
        if e.team != a.team:
            e.alive = False
    update_agent(m, a, 1 / 60, rng, tune)
    check("目标消失取消包抄", a.flank_goal is None)


def test_back_exposed_closes_distance():
    """目标背身时应该压上去偷，而不是原地横移。"""
    m, a, tgt = _setup()
    rng = random.Random(7)
    tune = dict(C.AI_PRESETS["hard"])
    start = math.hypot(tgt.x - a.x, tgt.y - a.y)
    for _ in range(120):                 # 2 秒
        tgt.yaw = math.atan2(tgt.y - a.y, tgt.x - a.x)   # 保持背身
        keep_alive(m, tgt)
        update_agent(m, a, 1 / 60, rng, tune)
    end = math.hypot(tgt.x - a.x, tgt.y - a.y)
    check("背身时会拉近距离", end < start - 0.5, f"{start:.2f} -> {end:.2f}")


def test_flank_disabled_by_config():
    m, a, tgt = _setup()
    rng = random.Random(7)
    tune = dict(C.AI_PRESETS["expert"])
    old = C.AI_FLANK_ENABLED
    C.AI_FLANK_ENABLED = False
    try:
        got = False
        for _ in range(600):
            tgt.yaw = math.atan2(tgt.y - a.y, tgt.x - a.x)
            update_agent(m, a, 1 / 60, rng, tune)
            if a.flank_goal is not None:
                got = True
                break
        check("关掉开关后不再包抄", got is False)
    finally:
        C.AI_FLANK_ENABLED = old


def test_agent_defaults():
    a = Agent(1, 1.0, 1.0)
    check("默认没有包抄目标", a.flank_goal is None)
    check("默认包抄计时为 0", a.flank_t == 0.0)


def main():
    print("=== AI 战术：偷背身 ===")
    test_back_exposed(); print()
    test_flank_point_behind(); print()
    test_flank_point_avoids_walls(); print()
    test_flank_triggers(); print()
    test_back_exposed_prefers_push_over_flank(); print()
    test_flank_cleared_on_low_hp(); print()
    test_flank_cleared_on_timeout(); print()
    test_flank_cleared_when_target_lost(); print()
    test_back_exposed_closes_distance(); print()
    test_flank_disabled_by_config(); print()
    test_agent_defaults(); print()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
