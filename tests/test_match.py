"""GEOM AIM 3v3 对战模式自检：构造 / 寻路连通 / 回合机 / AI 互殴 / 经济 / 自适应 / HUD 渲染。

直接跑：  python3 tests/test_match.py
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

import ai  # noqa: E402
import config as C  # noqa: E402
import engine  # noqa: E402
import hud  # noqa: E402
from ai import bfs_path, update_agent  # noqa: E402
from match import Match  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


G = engine.build_arena(C.ARENA_TILES_X, C.ARENA_TILES_Y, C.ARENA_ROOM_W, C.ARENA_ROOM_H)


# ---------------------------------------------------------------- 构造

def test_construct():
    m = Match(G, __import__("random").Random(), "normal")
    check("对战 6 人（1 玩家 + 2 队友 + 3 敌人）",
          len(m.agents) == 6, f"{len(m.agents)} 人")
    allies = [a for a in m.agents if a.team == 0]
    foes = [a for a in m.agents if a.team == 1]
    check("队 0 = 玩家影子 + 2 队友", len(allies) == 3 and m.player_agent in allies)
    check("队 1 = 3 敌人", len(foes) == 3)
    check("开局双方满员", m._alive(0) == 3 and m._alive(1) == 3)
    check("玩家影子标记 is_player", m.player_agent.is_player is True)
    check("出生点有两个（对角房间）",
          len(m.spawns) == 2 and not G.blocked(*m.spawns[0], 0.4)
          and not G.blocked(*m.spawns[1], 0.4))


# ---------------------------------------------------------------- 寻路连通

def test_pathing():
    m = Match(G, __import__("random").Random(), "normal")
    p0, p1 = m.spawns
    path = bfs_path(G, p0, p1)
    check("BFS 能连通两对角出生点（门洞 true 连通）", path is not None,
          f"路径长度 {len(path) if path else 'None'}")
    if path:
        # 路径必须全走在可站立格上
        ok = all(G.at(int(cx), int(cy)) == 0 for cx, cy in path)
        check("路径全程走在空地上（不穿墙）", ok)


# ---------------------------------------------------------------- 回合状态机

def test_round_state():
    m = Match(G, __import__("random").Random(), "normal")
    check("开局处于买枪阶段 prep", m.state == "prep")
    # 快进买枪时间
    m.update(C.MATCH_BUY_TIME + 0.1)
    check("买枪结束进入 live", m.state == "live")
    r0 = m.round_no
    # 直接让敌方全灭，应判我方胜、回合进入结算
    for a in m.agents:
        if a.team == 1:
            a.alive = False
    m._check_elimination()
    check("敌方全灭 -> 我方得分", m.score[0] == 1 and m.score[1] == 0)
    check("回合进入结算 round_end", m.state == "round_end")
    check("结算后 update 进入下一回合", (m.update(C.MATCH_END_PAUSE + 0.1) or True)
          and m.round_no == r0 + 1 and m.state == "prep")
    # 超时平局：让双方各有存活，强制 timeout
    before = list(m.score)
    m.state = "live"; m.timer = 0.0
    m._timeout()
    check("时间到人数相同 -> 平局、双方不得分",
          m.round_result == "draw" and m.score == before,
          f"平局前 {before} -> 平局后 {m.score}")


# ---------------------------------------------------------------- AI 互殴

def test_combat():
    rng = __import__("random").Random(123)
    m = Match(G, rng, "normal")
    m.state = "live"; m.timer = 999.0
    a = next(x for x in m.agents if x.team == 0 and not x.is_player)
    e = next(x for x in m.agents if x.team == 1 and x.alive)
    # 把敌人摆到 ally 正前方、清视线
    ex, ey = a.x + 8.0, a.y
    if not G.clear_line(a.x, a.y, ex, ey):
        for _ in range(50):
            spot = G.random_free(rng, pad=2.0)
            if spot and G.clear_line(a.x, a.y, spot[0], spot[1]):
                ex, ey = spot; break
    e.x, e.y = ex, ey
    a.yaw = math.atan2(ey - a.y, ex - a.x)
    hp0 = e.hp
    killed = False
    for _ in range(60 * 8):
        update_agent(m, a, 1 / 60, rng, m.ally_tune)
        if not e.alive:
            killed = True; break
    check("队友 AI 能击杀敌人", killed, f"HP {hp0} -> {e.hp:.0f}")

    # 反向：敌人 AI 打玩家影子
    m2 = Match(G, __import__("random").Random(7), "hard")
    m2.state = "live"; m2.timer = 999.0
    ea = next(x for x in m2.agents if x.team == 1 and x.alive)
    px, py = ea.x + 7.0, ea.y
    if G.clear_line(ea.x, ea.y, px, py):
        m2.player_agent.x, m2.player_agent.y = px, py
        m2.player_agent.alive = True; m2.player_dead = False; m2.player_hp = C.PLAYER_HP
        ea.yaw = math.atan2(py - ea.y, px - ea.x)
        for _ in range(60 * 10):
            update_agent(m2, ea, 1 / 60, rng, m2.enemy_tune)
            m2.player_agent.x, m2.player_agent.y = px, py
            m2.player_agent.alive = not m2.player_dead
            if m2.player_dead:
                break
        check("敌人 AI 能击倒玩家", m2.player_dead and m2.player_hp <= 0,
              f"player_hp={m2.player_hp}")
    else:
        check("敌人 AI 能击倒玩家", False, "无清视线，跳过")


# ---------------------------------------------------------------- 经济

def test_economy():
    from weapons import MATCH_WEAPONS
    m = Match(G, __import__("random").Random(), "normal")
    check("开局金钱 = ECON_START", m.player_money == C.ECON_START)
    check("钱不够买步枪被拒", m.player_buy("rifle") is False)
    # 模拟赢一局：team0 胜
    m._end_round(0)
    check("胜利后玩家进账（起始 + 胜场奖励）",
          m.player_money == C.ECON_START + C.ECON_WIN, f"${m.player_money}")
    # 真实流程里奖金会在下一回合的买枪阶段（prep）花掉
    m.state = "prep"
    ok = m.player_buy("rifle")
    expect = C.ECON_START + C.ECON_WIN - MATCH_WEAPONS["rifle"].price
    check("有钱能买步枪并正确扣款", ok and m.player_money == expect,
          f"剩 ${m.player_money}（应 ${expect}）")
    # 连败补偿递增
    m2 = Match(G, __import__("random").Random(), "normal")
    b0 = m2._loss_bonus(1)
    m2.loss_streak[1] = 4
    b1 = m2._loss_bonus(1)
    check("连败补偿随连败递增且有上限", b1 >= b0 and b1 <= C.ECON_LOSS_MAX)


def test_smoke_economy():
    """烟雾弹进经济：买枪阶段 $150 一颗；钱不够买不了；飞行直击造成伤害。"""
    from nades import SmokeGrenade
    m = Match(G, __import__("random").Random(), "normal")
    check("开局对战不免费配给烟（靠经济买）", m.player_money == C.ECON_START)
    # 钱不够买不了
    m.player_money = 100
    check("钱不够（$100 < $150）买不了烟", m.player_buy_smoke() is False)
    check("买失败不扣钱", m.player_money == 100, f"${m.player_money}")
    # 钱够能买，扣 $150
    m.player_money = 800
    ok = m.player_buy_smoke()
    check("钱够能买到一颗烟", ok and m.player_money == 800 - C.SMOKE_PRICE,
          f"剩 ${m.player_money}")
    # 非买枪阶段不能买
    m.state = "live"
    money_live = m.player_money
    check("交火阶段不能买烟", m.player_buy_smoke() is False)
    check("交火阶段买烟不扣钱", m.player_money == money_live)

    # 飞行直击造成伤害（非友伤）
    enemy = next(a for a in m.agents if a.team == 1)
    enemy.hp, enemy.alive = 100, True
    ally = next(a for a in m.agents if a.team == 0 and not a.is_player)
    ally.hp, ally.alive = 100, True
    gren = SmokeGrenade(enemy.x, enemy.y, 0.3, 0.0, 0.0, 0.0, team=0)
    m.smokes.grenades.append(gren)
    m._smoke_direct_hits()
    check("烟雾弹直击敌人扣血", enemy.hp == 100 - C.SMOKE_DIRECT_DMG, f"hp={enemy.hp}")
    check("烟雾弹不对队友造成伤害", ally.hp == 100, f"hp={ally.hp}")
    # 起烟后的烟不再造成直击伤害
    gren._popped = True
    enemy.hp = 100
    m._smoke_direct_hits()
    check("起烟后的烟不再直击造成伤害", enemy.hp == 100, f"hp={enemy.hp}")


def test_ai_buys_smoke():
    """队友 AI 和敌人 AI 都会在买枪阶段买烟（最多带 2 颗）。"""
    m = Match(G, __import__("random").Random(), "normal")   # __init__ 已跑过 start_round
    ai_agents = [a for a in m.agents if not a.is_player]
    check("非玩家 AI 都买到了烟雾弹", all(a.smoke_charges > 0 for a in ai_agents),
          f"各自携带量={[a.smoke_charges for a in ai_agents]}")
    check("AI 携带量上限 2 颗", all(a.smoke_charges <= 2 for a in ai_agents))
    # 玩家影子不在此列
    check("玩家影子不自动买烟", m.player_agent.smoke_charges == 0)
    # 钱确实被扣了（买枪 + 买烟）
    spent = C.ECON_START - ai_agents[0].money
    check("买烟确实花了钱", spent >= 0 and ai_agents[0].money < C.ECON_START,
          f"花了 ${spent}")


def test_ai_throws_smoke():
    """交火中 AI 朝可见敌人扔烟：场上有烟、队伍正确、携带量递减。

    用烟规则收紧之后，这里必须同时满足：过了开局冷静期、距离落在
    SMOKE_AI_MIN_DIST~MAX_DIST 之间（近距离不扔，否则糊自己的视线）。
    出手前还有一段随机延迟，所以循环要留够时间。
    """
    rng = __import__("random").Random(55)
    m = Match(G, rng, "normal")
    m.state = "live"; m.timer = 999.0
    m.live_t = C.SMOKE_AI_CALM + 1.0        # 已过开局冷静期
    a = next(x for x in m.agents if x.team == 0 and not x.is_player)
    e = next(x for x in m.agents if x.team == 1 and x.alive)
    # 只留这一个敌人，避免 pick_target 选中更近的其他人导致距离不受控
    for other in m.agents:
        if other.team == 1 and other is not e:
            other.alive = False
    e.x, e.y = a.x + (C.SMOKE_AI_MIN_DIST + 6.0), a.y
    a.yaw = math.atan2(e.y - a.y, e.x - a.x)
    a.smoke_charges = 2
    a.smoke_cd = 0.0
    m.smokes.clear()

    old_vis, old_chance = ai._visible, C.SMOKE_AI_CHANCE
    ai._visible = lambda mm, aa, ee: True   # 视线打桩，不依赖地图几何
    C.SMOKE_AI_CHANCE = 1.0                 # 去掉概率抖动，专测"会不会扔"
    try:
        before = a.smoke_charges
        threw = False
        for _ in range(60 * 6):             # 留出随机延迟（最多 1.5s）的时间
            update_agent(m, a, 1 / 60, rng, m.ally_tune)
            if any(g.team == 0 for g in m.smokes.grenades):
                threw = True
                break
        check("AI 朝敌人扔出了烟", threw)
        check("扔出的烟归属投掷者队伍（team 0）",
              any(g.team == 0 for g in m.smokes.grenades))
        check("扔完携带量递减", a.smoke_charges < before,
              f"{before} -> {a.smoke_charges}")
    finally:
        ai._visible = old_vis
        C.SMOKE_AI_CHANCE = old_chance


# ---------------------------------------------------------------- 自适应

def test_adaptive():
    m = Match(G, __import__("random").Random(), "normal")
    base = C.AI_PRESETS[m.difficulty]
    # 把 adapt 拉到极端，tune 应仍在 ±band 的倍率范围内
    for val in (-1.0, 1.0):
        m.adapt = val
        m._apply_tune()
        k = 1.0 + val * C.AI_ADAPT_BAND
        lo, hi = min(1.0, k), max(1.0, k)
        in_band = (base["reaction"] / hi) <= m.enemy_tune["reaction"] <= (base["reaction"] / lo)
        check(f"自适应 adapt={val:+.0f} 时 reaction 仍在 ±{int(C.AI_ADAPT_BAND*100)}% 带内",
              in_band, f"reaction={m.enemy_tune['reaction']:.3f}")


# ---------------------------------------------------------------- HUD / 渲染

def test_hud():
    pygame.init()
    screen = pygame.display.set_mode((C.WINDOW_W, C.WINDOW_H))
    r = engine.Renderer(C.WINDOW_W, C.WINDOW_H, C.H_FOV_DEG)
    cam = engine.Camera(*G.center_free())

    # 标题界面渲染不崩
    try:
        g = __import__("main").Game()
        g.state = "title"
        g.draw()
        drawn_title = True
    except Exception as e:  # noqa
        drawn_title = False
        print("   title 渲染异常:", e)
    check("标题界面可渲染", drawn_title)

    # 对战 HUD + 买枪菜单 + 结算 + match_end 全渲染不崩
    g.start_match()
    try:
        g.draw()                       # prep 阶段 -> 画买枪菜单
        g.match.state = "live"
        g.draw()
        g.match.state = "round_end"
        g.match.round_result = "win"
        g.draw()
        g.match.state = "match_end"
        g.draw()
        drawn_match = True
    except Exception as e:  # noqa
        drawn_match = False
        print("   match HUD 渲染异常:", e)
    check("对战 HUD（含买枪/结算/结束）可渲染", drawn_match)


# ---------------------------------------------------------------- 复活镜头复位

def test_respawn_camera():
    g = __import__("main").Game()
    g.start_match()
    # 跑过买枪进 live
    for _ in range(int((C.MATCH_BUY_TIME + 0.2) / 0.05)):
        g.update(0.05)
    check("live 阶段玩家镜头在我方出生点附近",
          math.hypot(g.cam.x - g.match.spawns[0][0],
                     g.cam.y - g.match.spawns[0][1]) < 3.0)
    # 阵亡：先原地倒地，DEATH_CAM_HOLD 秒之后才切到队友视角
    g.match.player_dead = True
    g.match.player_hp = 0
    x0, y0 = g.cam.x, g.cam.y
    for _ in range(int(0.5 / 0.05)):
        g.update(0.05)
    check("阵亡后先倒地，镜头留在死亡点",
          math.hypot(g.cam.x - x0, g.cam.y - y0) < 1e-9)
    for _ in range(int((C.DEATH_CAM_HOLD + 0.3) / 0.05)):
        g.update(0.05)
    spec = g.match.spectate_target()
    if spec is not None:
        moved = math.hypot(g.cam.x - spec.x, g.cam.y - spec.y) < 0.5
        check("倒地结束后镜头切到观战队友", moved)
    # 进入下一回合：镜头应被拽回我方出生点
    g.match.start_round()
    g.update(0.05)
    back = math.hypot(g.cam.x - g.match.spawns[0][0],
                      g.cam.y - g.match.spawns[0][1]) < 1.0
    check("新回合镜头复位到我方出生点", back)


def main():
    test_construct(); print()
    test_pathing(); print()
    test_round_state(); print()
    test_combat(); print()
    test_economy(); print()
    test_smoke_economy(); print()
    test_ai_buys_smoke(); print()
    test_ai_throws_smoke(); print()
    test_adaptive(); print()
    test_hud(); print()
    test_respawn_camera(); print()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
