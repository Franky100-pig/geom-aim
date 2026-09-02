"""GEOM AIM 积分赛（5v5 连续重生 TDM）自检。

覆盖：5v5 构造 / 3x3 地图 / 无经济自由换枪 / 击杀计分 / 重生延迟与无敌 /
      先到 25 杀获胜 / 蹲下 / HUD 渲染不崩。

直接跑：  python3 tests/test_score.py
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
from match import Match  # noqa: E402
from player import Player  # noqa: E402
from weapons import match_weapon  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


# 积分赛用 3x3 大地图；回合制对沿用 2x2 小地图
GS = engine.build_arena(C.SCORE_MAP_TILES_X, C.SCORE_MAP_TILES_Y,
                        C.SCORE_MAP_ROOM_W, C.SCORE_MAP_ROOM_H)
GM = engine.build_arena(C.MATCH_TILES_X, C.MATCH_TILES_Y,
                        C.MATCH_ROOM_W, C.MATCH_ROOM_H)


def new_score(seed=7):
    return Match(GS, random.Random(seed), "normal", None, mode="score")


def bots(m, team):
    return [a for a in m.agents if a.team == team and not a.is_player]


# ---------------------------------------------------------------- 构造

def test_build_5v5():
    m = new_score()
    t0 = [a for a in m.agents if a.team == 0]
    t1 = [a for a in m.agents if a.team == 1]
    check("积分赛共 10 人", len(m.agents) == 10, f"实际 {len(m.agents)}")
    check("我方 5 人（你 + 4 AI）", len(t0) == 5, f"实际 {len(t0)}")
    check("敌方 5 人", len(t1) == 5, f"实际 {len(t1)}")
    check("玩家影子在我方", m.player_agent is not None
          and m.player_agent.is_player and m.player_agent.team == 0)
    check("我方 AI 队友 4 个", len(bots(m, 0)) == 4, f"实际 {len(bots(m, 0))}")
    check("team_size = 5", m.team_size == C.SCORE_TEAM_SIZE)


def test_live_immediately():
    """积分赛没有买枪阶段，开局即交火。"""
    m = new_score()
    check("开局状态 live（无 prep 买枪阶段）", m.state == "live", f"实际 {m.state}")
    check("mode = score", m.mode == "score")
    check("击杀数从 0:0 开始", m.team_kills == [0, 0], f"实际 {m.team_kills}")
    check("全员满血存活", all(a.alive and a.hp == C.AGENT_HP for a in m.agents))
    check("全员开局无无敌", all(a.invuln == 0.0 for a in m.agents))


def test_map_bigger():
    """积分赛 10 人，地图必须比 3v3 的 2x2 大。"""
    check("积分赛地图比回合制大",
          GS.w > GM.w and GS.h > GM.h,
          f"score {GS.w}x{GS.h} vs match {GM.w}x{GM.h}")
    m = new_score()
    check("双方出生点不同", m.spawns[0] != m.spawns[1])
    check("出生点可站立（非墙里）",
          not GS.blocked(*m.spawns[0], 0.4) and not GS.blocked(*m.spawns[1], 0.4))


# ---------------------------------------------------------------- 无经济 / 换枪

def test_free_swap():
    """积分赛无经济：1-5 自由换枪，不花钱。"""
    m = new_score()
    money_before = m.player_money
    ok = m.player_swap("awp")
    check("换枪成功", ok)
    check("武器已换成 AWP", m.player_agent.weapon.key == "awp",
          f"实际 {m.player_agent.weapon.key}")
    check("换枪不扣钱（无经济）", m.player_money == money_before,
          f"{money_before} -> {m.player_money}")
    check("再换回步枪", m.player_swap("rifle") and m.player_agent.weapon.key == "rifle")
    check("非法枪名返回 False", m.player_swap("不存在的枪") is False)


# ---------------------------------------------------------------- 计分

def test_kill_scores():
    """击杀给击杀方队伍加分。"""
    m = new_score()
    killer = bots(m, 0)[0]
    victim = bots(m, 1)[0]
    guard = 0
    while victim.alive and guard < 60:
        m.apply_damage(killer, victim, False)
        guard += 1
    check("目标已阵亡", not victim.alive)
    check("我方 +1 分", m.team_kills[0] == 1, f"实际 {m.team_kills}")
    check("敌方仍 0 分", m.team_kills[1] == 0)

    # 反向：敌人击杀我方 AI，敌方 +1
    k2 = bots(m, 1)[1]
    v2 = bots(m, 0)[1]
    guard = 0
    while v2.alive and guard < 60:
        m.apply_damage(k2, v2, False)
        guard += 1
    check("敌方击杀后敌方 +1 分", m.team_kills[1] == 1, f"实际 {m.team_kills}")


# ---------------------------------------------------------------- 重生 / 无敌

def test_bot_respawn_delay():
    """AI 阵亡后要等 SCORE_RESPAWN_DELAY 才复活，不是瞬间复活。"""
    m = new_score()
    killer = bots(m, 0)[0]
    victim = bots(m, 1)[0]
    guard = 0
    while victim.alive and guard < 60:
        m.apply_damage(killer, victim, False)
        guard += 1
    check("阵亡后进入重生倒计时",
          close(victim.respawn_timer, C.SCORE_RESPAWN_DELAY),
          f"respawn_timer={victim.respawn_timer}")

    m._update_score(0.1)                      # 只推进一点点
    check("延迟未到 → 仍阵亡", not victim.alive)

    m._update_score(C.SCORE_RESPAWN_DELAY)    # 推过延迟
    check("延迟到 → 已重生", victim.alive)
    check("重生后满血", victim.hp == C.AGENT_HP, f"hp={victim.hp}")
    check("重生后带无敌", victim.invuln > 0, f"invuln={victim.invuln}")


def test_invuln_blocks_damage():
    """无敌期间不吃伤害。"""
    m = new_score()
    shooter = bots(m, 1)[0]
    victim = bots(m, 0)[0]
    victim.invuln = C.SCORE_INVULN
    hp_before = victim.hp
    m.apply_damage(shooter, victim, False)
    check("AI 无敌期间免伤", victim.hp == hp_before, f"{hp_before} -> {victim.hp}")

    # 玩家的影子 Agent 同样享受无敌
    m2 = new_score()
    m2.player_agent.invuln = C.SCORE_INVULN
    php = m2.player_hp
    m2.apply_damage(bots(m2, 1)[0], m2.player_agent, False)
    check("玩家无敌期间免伤", m2.player_hp == php, f"{php} -> {m2.player_hp}")

    # 无敌结束后恢复受伤
    m3 = new_score()
    v = bots(m3, 0)[0]
    v.invuln = 0.0
    hp0 = v.hp
    m3.apply_damage(bots(m3, 1)[0], v, False)
    check("无敌结束后正常受伤", v.hp < hp0, f"{hp0} -> {v.hp}")


def test_player_death_and_respawn():
    """玩家阵亡 → 倒计时 → 满血带无敌重生。"""
    m = new_score()
    shooter = bots(m, 1)[0]
    guard = 0
    while m.player_hp > 0 and guard < 60:
        m.apply_damage(shooter, m.player_agent, False)
        guard += 1
    check("玩家阵亡", m.player_dead and m.player_hp == 0)
    check("计入阵亡数", m.stats["deaths"] == 1, f"deaths={m.stats['deaths']}")
    check("敌方得分", m.team_kills[1] == 1, f"实际 {m.team_kills}")
    check("玩家重生倒计时已排好",
          close(m.player_respawn, C.SCORE_RESPAWN_DELAY),
          f"player_respawn={m.player_respawn}")
    check("玩家影子也排了倒计时",
          close(m.player_agent.respawn_timer, C.SCORE_RESPAWN_DELAY),
          f"respawn_timer={m.player_agent.respawn_timer}")

    m._update_score(0.1)
    check("未到时间仍阵亡", m.player_dead)

    m._update_score(C.SCORE_RESPAWN_DELAY)
    check("到时间后重生", not m.player_dead)
    check("重生后满血", m.player_hp == C.PLAYER_HP, f"hp={m.player_hp}")
    check("重生后带无敌", m.player_agent.invuln > 0,
          f"invuln={m.player_agent.invuln}")


# ---------------------------------------------------------------- 胜负

def test_win_at_25():
    """先到 25 杀的队伍获胜。"""
    m = new_score()
    m.team_kills[0] = C.SCORE_KILL_TARGET
    check("未达标时不结束", m.state != "match_end")
    m._update_score(0.016)
    check(f"我方到 {C.SCORE_KILL_TARGET} 杀 → 比赛结束", m.state == "match_end",
          f"state={m.state}")
    check("我方获胜", m.player_won is True)

    m2 = new_score()
    m2.team_kills[1] = C.SCORE_KILL_TARGET
    m2._update_score(0.016)
    check("敌方达标 → 比赛结束", m2.state == "match_end")
    check("我方失败", m2.player_won is False)


# ---------------------------------------------------------------- 蹲

class FakeKeys(dict):
    """按键状态替身：没按过的键一律 False（pygame 键码很大，不能用 list）。"""

    def __missing__(self, k):
        return False


def test_crouch():
    """Ctrl 蹲下：收紧扩散、缩小命中轮廓。"""
    pygame.init()
    p = Player()
    p.weapon = match_weapon("rifle")
    cam = engine.Camera(*GS.center_free())

    keys = FakeKeys()
    p.update_move(0.016, cam, GS, keys)
    check("默认站立", p.crouch is False)
    stand_spread = p.spread

    keys[pygame.K_LCTRL] = True
    p.update_move(0.016, cam, GS, keys)
    check("按住 Ctrl → 蹲下", p.crouch is True)
    check("蹲下后扩散更小", p.spread < stand_spread,
          f"{stand_spread:.5f} -> {p.spread:.5f}")

    keys[pygame.K_LCTRL] = False
    keys[pygame.K_RCTRL] = True
    p.update_move(0.016, cam, GS, keys)
    check("右 Ctrl 也能蹲", p.crouch is True)

    keys[pygame.K_RCTRL] = False
    p.update_move(0.016, cam, GS, keys)
    check("松开 Ctrl → 站起", p.crouch is False)

    check("蹲下命中轮廓更小", C.BOT_H * C.CROUCH_H_MUL < C.BOT_H)


# ---------------------------------------------------------------- HUD

def test_hud():
    """积分赛 HUD 在各种状态下都能渲染，不崩。"""
    pygame.init()
    pygame.display.set_mode((C.WINDOW_W, C.WINDOW_H))

    g = __import__("main").Game()
    g.start_score()
    check("start_score 后进入 play", g.state == "play")
    check("积分赛用 3x3 地图", g.gmap.w == GS.w and g.gmap.h == GS.h,
          f"{g.gmap.w}x{g.gmap.h}")
    check("开局武器已同步给玩家", g.player.weapon is not None)

    try:
        g.draw()                                   # 正常交火中
        drawn_live = True
        err_live = ""
    except Exception as e:  # noqa
        drawn_live, err_live = False, str(e)
    check("交火中 HUD 可渲染", drawn_live, err_live)

    try:
        g.match.player_dead = True                 # 阵亡观战 + 重生倒计时
        g.match.player_respawn = 1.2
        g.draw()
        drawn_dead = True
        err_dead = ""
    except Exception as e:  # noqa
        drawn_dead, err_dead = False, str(e)
    check("阵亡 HUD 可渲染", drawn_dead, err_dead)

    try:
        g.match.player_dead = False
        g.match.player_agent.invuln = 2.5          # 无敌提示
        g.draw()
        drawn_inv = True
        err_inv = ""
    except Exception as e:  # noqa
        drawn_inv, err_inv = False, str(e)
    check("无敌提示可渲染", drawn_inv, err_inv)

    try:
        g.match.team_kills = [25, 17]              # 结算面板
        g.match.state = "match_end"
        g.draw()
        drawn_end = True
        err_end = ""
    except Exception as e:  # noqa
        drawn_end, err_end = False, str(e)
    check("结算面板可渲染", drawn_end, err_end)


# ---------------------------------------------------------------- 主流程

def main():
    test_build_5v5(); print()
    test_live_immediately(); print()
    test_map_bigger(); print()
    test_free_swap(); print()
    test_kill_scores(); print()
    test_bot_respawn_delay(); print()
    test_invuln_blocks_damage(); print()
    test_player_death_and_respawn(); print()
    test_win_at_25(); print()
    test_crouch(); print()
    test_hud(); print()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
