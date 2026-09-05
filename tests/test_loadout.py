"""3v3 武器库存与切枪自检。

背景：原先 _buy() 是直接替换 a.weapon，买了第二把枪第一把就消失。
现在：每回合开始库存重置回手枪（CS 式经济局）；同一回合内买的多把枪
用 C 键循环切换，买枪阶段和交火阶段都行；1-5 只在买枪阶段负责购买。

直接跑：  python3 tests/test_loadout.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random  # noqa: E402

import config as C  # noqa: E402
import engine  # noqa: E402
from match import Match  # noqa: E402
from weapons import MATCH_WEAPONS, match_weapon  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


G = engine.build_arena(C.ARENA_TILES_X, C.ARENA_TILES_Y, C.ARENA_ROOM_W, C.ARENA_ROOM_H)


def fresh(mode: str = "match", seed: int = 7) -> Match:
    return Match(G, random.Random(seed), "normal", mode=mode)


# ---------------------------------------------------------------- 库存

def test_default_loadout():
    m = fresh()
    p = m.player_agent
    check("开局库存只有手枪", p.loadout == ["pistol"], f"{p.loadout}")
    check("开局手持手枪", p.weapon.key == "pistol", p.weapon.key)
    check("AI 开局也只有手枪",
          all(a.loadout == ["pistol"] for a in m.agents if not a.is_player))


def test_buy_adds_to_loadout():
    """买第二把枪：两把都在库存里，当前武器是新买的那把。"""
    m = fresh()
    m.player_money = 99999
    check("买步枪成功", m.player_buy("rifle") is True)
    check("库存含 pistol + rifle",
          sorted(m.player_agent.loadout) == ["pistol", "rifle"],
          f"{m.player_agent.loadout}")
    check("当前武器 = 步枪", m.player_agent.weapon.key == "rifle")

    m.player_money = 99999
    check("再买 AWP 成功", m.player_buy("awp") is True)
    check("三把枪都在库存",
          sorted(m.player_agent.loadout) == ["awp", "pistol", "rifle"],
          f"{m.player_agent.loadout}")
    check("当前武器 = AWP", m.player_agent.weapon.key == "awp")


def test_buy_owned_is_free_switch():
    """已拥有的枪再按一次 = 免费切回去，不重复扣钱。"""
    m = fresh()
    m.player_money = 99999
    m.player_buy("rifle")
    m.player_buy("awp")
    m.player_money = 5000
    before = m.player_money

    check("切回已拥有的步枪 → 成功", m.player_select("rifle") is True)
    check("切换不花钱", m.player_money == before, f"{before} -> {m.player_money}")
    check("当前武器 = 步枪", m.player_agent.weapon.key == "rifle")
    check("库存数量不变（没重复添加）", len(m.player_agent.loadout) == 3,
          f"{m.player_agent.loadout}")


def test_switch_during_live():
    """交火阶段（state=live）也能切 —— 这正是原来那个 bug。"""
    m = fresh()
    m.player_money = 99999
    m.player_buy("rifle")
    m.player_buy("awp")
    m.state = "live"

    check("交火中切回手枪", m.player_select("pistol") is True)
    check("当前武器 = 手枪", m.player_agent.weapon.key == "pistol")
    check("交火中切回步枪", m.player_select("rifle") is True)
    check("当前武器 = 步枪", m.player_agent.weapon.key == "rifle")


def test_select_unowned_fails():
    m = fresh()
    check("没买过的枪切不了", m.player_select("awp") is False)
    check("武器保持不变", m.player_agent.weapon.key == "pistol")
    check("库存没有被污染", m.player_agent.loadout == ["pistol"], f"{m.player_agent.loadout}")


def test_buy_unaffordable():
    m = fresh()
    m.player_money = 0
    check("没钱买步枪失败", m.player_buy("rifle") is False)
    check("失败后库存不变", m.player_agent.loadout == ["pistol"])
    check("失败后武器不变", m.player_agent.weapon.key == "pistol")


def test_ai_no_rebuy():
    """AI 已经有步枪就不再重复买（省钱，也让经济更像 CS）。"""
    m = fresh()
    a = [x for x in m.agents if not x.is_player][0]
    a.money = 99999
    m._ai_buy(a)
    first_spend = 99999 - a.money
    check("AI 第一次买枪花了钱", first_spend > 0, f"花了 {first_spend}")

    money_before = a.money
    m._ai_buy(a)
    check("已有武器时不再重复扣钱", a.money == money_before,
          f"{money_before} -> {a.money}")
    check("AI 库存不重复", len(a.loadout) == len(set(a.loadout)), f"{a.loadout}")


def test_score_mode_still_free():
    """积分赛照旧 1-5 免费全武器换（不受库存限制）。"""
    m = fresh(mode="score")
    check("积分赛切 AWP 成功", m.player_swap("awp") is True)
    check("武器 = AWP", m.player_agent.weapon.key == "awp")
    check("切连狙成功", m.player_swap("dmr") is True)
    check("武器 = 连狙", m.player_agent.weapon.key == "dmr")


# ---------------------------------------------------------------- 联机快照

def test_snapshot_sync():
    """库存要跟着快照走，客户端才知道自己有几把枪。"""
    m = fresh()
    m.player_money = 99999
    m.player_buy("rifle")
    m.player_select("pistol")

    snap = m.snapshot()
    entry = [a for a in snap["agents"] if a["is_local"]][0]
    check("快照带库存", sorted(entry.get("loadout", [])) == ["pistol", "rifle"],
          f"{entry.get('loadout')}")
    check("快照武器用 key（不是中文名）",
          entry["weapon"] in MATCH_WEAPONS, f"{entry['weapon']}")

    m2 = fresh(seed=3)
    m2.apply_snapshot(snap)
    p2 = m2.player_agent
    check("客户端还原库存", sorted(p2.loadout) == ["pistol", "rifle"], f"{p2.loadout}")
    check("客户端还原当前武器", p2.weapon.key == "pistol", p2.weapon.key)


# ---------------------------------------------------------------- 真人输入（联机）

def test_human_input_weapon():
    """联机真人发来的换枪请求：已拥有就切，买枪阶段才允许新买。"""
    m = fresh()
    # 模拟一个联网真人接入（_drive_humans 只驱动 controller == "human" 的 Agent）
    a = [x for x in m.agents if x.controller == "ai"][0]
    a.controller = "human"
    a.money = 99999

    m.human_inputs[a] = dict(weapon="pistol")
    m._drive_humans(0.016)
    check("自带的枪 → 直接切换", a.weapon.key == "pistol", a.weapon.key)

    m.human_inputs[a] = dict(weapon="awp")
    m._drive_humans(0.016)
    check("买枪阶段新枪 → 买入并装备", a.weapon.key == "awp", a.weapon.key)
    check("新枪进库存", "awp" in a.loadout, f"{a.loadout}")

    m.state = "live"
    m.human_inputs[a] = dict(weapon="dmr")
    m._drive_humans(0.016)
    check("交火中不能凭空买没拥有的枪", a.weapon.key == "awp", a.weapon.key)

    m.human_inputs[a] = dict(weapon="pistol")
    m._drive_humans(0.016)
    check("交火中能切回已拥有的枪", a.weapon.key == "pistol", a.weapon.key)


def test_round_reset():
    """每一局（回合）都重置：从没有买过的枪开始，只带免费手枪。"""
    m = fresh()
    m.player_money = 99999
    m.player_buy("rifle")
    m.player_buy("awp")
    check("买完手里是 AWP", m.player_agent.weapon.key == "awp")

    m.start_round()
    p = m.player_agent
    check("新回合库存重置回手枪", p.loadout == ["pistol"], f"{p.loadout}")
    check("新回合手持手枪", p.weapon.key == "pistol", p.weapon.key)
    check("新回合弹匣重置", p.mags == {"pistol": MATCH_WEAPONS["pistol"].mag},
          f"{p.mags}")

    ai = [x for x in m.agents if not x.is_player][0]
    check("AI 新回合同样重置", ai.loadout == ["pistol"], f"{ai.loadout}")


def test_cycle_weapon():
    """C 键：在已买的枪里循环切换；只有一把时不切；切枪打断换弹。"""
    m = fresh()
    p = m.player_agent
    check("只有手枪时 C 不切换", m.player_cycle() is False)

    m.player_money = 99999
    m.player_buy("rifle")          # 现在: pistol -> rifle
    check("C 从手枪切到步枪", p.weapon.key == "rifle", p.weapon.key)
    check("C 再切到下一把", m.player_cycle() is True)
    check("库存只有两把 → 又回到手枪", p.weapon.key == "pistol", p.weapon.key)

    # 循环顺序：pistol -> rifle -> pistol -> ...
    m.player_cycle()
    check("循环回步枪", p.weapon.key == "rifle", p.weapon.key)

    # 切枪打断换弹（先打空弹匣才允许换）
    from ai import start_reload
    p.mags[p.weapon.key] = 1
    check("未满弹匣能起换弹", start_reload(p) is True)
    check("换弹中", p.reload_t > 0, f"{p.reload_t:.2f}")
    m.player_cycle()
    check("切枪打断换弹", p.reload_t == 0.0, f"{p.reload_t}")
    check("打断后武器已切换", p.weapon.key == "pistol", p.weapon.key)


def main():
    print("=== 3v3 武器库存 / 切枪 ===")
    test_default_loadout(); print()
    test_buy_adds_to_loadout(); print()
    test_buy_owned_is_free_switch(); print()
    test_switch_during_live(); print()
    test_select_unowned_fails(); print()
    test_buy_unaffordable(); print()
    test_ai_no_rebuy(); print()
    test_score_mode_still_free(); print()
    test_snapshot_sync(); print()
    test_human_input_weapon(); print()
    test_round_reset(); print()
    test_cycle_weapon(); print()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
