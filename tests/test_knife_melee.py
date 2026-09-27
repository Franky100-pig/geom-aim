"""回归测试：近战刀 + 手枪改为可购买 + 没买枪默认用刀。

锁住三条契约：
1. 3v3 每回合开局默认武器是刀（不是枪），且刀免费、不耗弹、不换弹。
2. 手枪现在是"可购买"武器（price>0、melee=False），不再是默认免费武器。
3. 近战能打：贴脸（KNIFE_RANGE 内、朝向对准）能造成伤害；超出范围打不到。
   近战永远允许开火（不耗弹、不换弹）。

直接跑：  python3 tests/test_knife_melee.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as C  # noqa: E402
import main  # noqa: E402
from weapons import MATCH_WEAPONS  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def _setup_knife_scenario():
    """搭一个确定性近战场景：玩家与敌人同处一个开阔格，玩家朝 +x 看。"""
    g = main.Game()
    g.start_match()
    m = g.match
    pa = m.player_agent

    knife = MATCH_WEAPONS["knife"]
    pa.weapon = knife
    pa.mags = {"knife": 0}
    g.player.weapon = knife
    g.player.ads = False

    fx, fy = g.gmap.center_free()
    g.cam.x, g.cam.y = fx, fy
    g.cam.yaw = 0.0
    g.cam.eff_yaw = 0.0

    assert m.enemies(), "start_match 后应有敌方 Agent 供测试"
    enemy = m.enemies()[0]
    enemy.alive = True
    enemy.hp = C.AGENT_HP
    return g, m, pa, enemy, fx, fy


def test_default_loadout_is_knife():
    """3v3 每回合开局默认武器必须是刀（免费、近战、无弹匣）。"""
    g = main.Game()
    g.start_match()
    pa = g.match.player_agent

    check("开局默认武器是刀", pa.weapon.key == "knife", pa.weapon.key)
    check("刀免费（price=0）", MATCH_WEAPONS["knife"].price == 0)
    check("刀是近战武器（melee=True）", MATCH_WEAPONS["knife"].melee is True)
    check("刀无弹匣（mag=0）", MATCH_WEAPONS["knife"].mag == 0)
    check("刀不进弹匣逻辑（mags 仅 knife:0）", pa.mags == {"knife": 0},
          str(pa.mags))


def test_pistol_purchasable_not_default():
    """手枪现在是可购买的付费武器，不再是默认免费起手。"""
    pistol = MATCH_WEAPONS["pistol"]
    check("手枪需花钱购买（price>0）", pistol.price > 0, f"{pistol.price}")
    check("手枪是枪（melee=False）", pistol.melee is False)
    check("手枪有弹匣（mag>0）", pistol.mag > 0, f"{pistol.mag}")

    g = main.Game()
    g.start_match()
    pa = g.match.player_agent
    check("开局默认不是手枪", pa.weapon.key != "pistol", pa.weapon.key)


def test_melee_always_can_shoot():
    """近战不耗弹、不换弹：空仓也永远允许挥刀（不会卡在换弹中）。"""
    g, m, pa, _enemy, _fx, _fy = _setup_knife_scenario()
    pa.mags = {"knife": 0}
    pa.reload_t = 0.0

    check("空仓也能挥刀（_match_can_shoot=True）", g._match_can_shoot() is True)

    # 模拟"换弹中"状态，枪会被卡住，但刀不该被卡
    pa.reload_t = C.RELOAD_TIME
    check("换弹中也照样能挥刀", g._match_can_shoot() is True)


def test_knife_hits_in_range():
    """贴脸且朝向对准：挥刀应造成伤害（身体 50）。"""
    g, m, pa, enemy, fx, fy = _setup_knife_scenario()
    # 敌人就在正前方 0.4 格（< KNIFE_RANGE 1.9），同处一个开阔格保证视线无墙
    enemy.x, enemy.y = fx + 0.4, fy

    before = enemy.hp
    g._do_melee()

    check("贴脸挥刀造成伤害", enemy.hp < before, f"{before} -> {enemy.hp}")
    check("身体刀伤=50", enemy.hp == before - MATCH_WEAPONS["knife"].damage,
          f"{enemy.hp}")


def test_knife_misses_out_of_range():
    """超出 KNIFE_RANGE：挥刀打不到，敌人血不变。"""
    g, m, pa, enemy, fx, fy = _setup_knife_scenario()
    enemy.x, enemy.y = fx + 3.0, fy   # 3.0 > KNIFE_RANGE(1.9)

    before = enemy.hp
    g._do_melee()

    check("超距离挥刀打不到", enemy.hp == before, f"{before} -> {enemy.hp}")


def run_tests():
    print("=== 近战刀 / 手枪可购买 回归 ===")
    test_default_loadout_is_knife(); print()
    test_pistol_purchasable_not_default(); print()
    test_melee_always_can_shoot(); print()
    test_knife_hits_in_range(); print()
    test_knife_misses_out_of_range(); print()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
