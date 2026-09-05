"""弹药与换弹自检（仅 3v3 对战生效，练习/积分赛不受限）。

直接跑：  python3 tests/test_ammo.py
"""

from __future__ import annotations

import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math  # noqa: E402

import config as C  # noqa: E402
import engine  # noqa: E402
from ai import ammo_of, start_reload, tick_reload, update_agent  # noqa: E402
from match import Match  # noqa: E402
from weapons import MATCH_WEAPONS  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


G = engine.build_arena(C.ARENA_TILES_X, C.ARENA_TILES_Y, C.ARENA_ROOM_W, C.ARENA_ROOM_H)


def fresh(mode: str = "match", seed: int = 7) -> Match:
    return Match(G, random.Random(seed), "normal", mode=mode)


def _human_agent(m: Match):
    """挑一个 AI Agent 伪装成联网真人（_drive_humans 只驱动 human）。"""
    a = [x for x in m.agents if x.controller == "ai"][0]
    a.controller = "human"
    a.money = 99999
    return a


# ---------------------------------------------------------------- 基础

def test_mag_sizes():
    check("手枪 12 发", MATCH_WEAPONS["pistol"].mag == 12)
    check("步枪 30 发", MATCH_WEAPONS["rifle"].mag == 30)
    check("狙击 5 发", MATCH_WEAPONS["awp"].mag == 5)
    m = fresh()
    p = m.player_agent
    check("开局手枪满弹", ammo_of(p) == 12, f"{ammo_of(p)}")
    check("开局没在换弹", p.reload_t == 0.0)


def test_fire_consumes():
    m = fresh()
    a = _human_agent(m)
    m._buy(a, "rifle")
    before = ammo_of(a)
    m.fire_human(a)
    check("每开一枪扣一发", ammo_of(a) == before - 1,
          f"{before} -> {ammo_of(a)}")
    m.fire_human(a)
    m.fire_human(a)
    check("连开三枪扣三发", ammo_of(a) == before - 3, f"{ammo_of(a)}")


def test_empty_auto_reload():
    m = fresh()
    a = _human_agent(m)
    m._buy(a, "rifle")
    a.mags["rifle"] = 1
    shots0 = a.shots
    m.fire_human(a)                       # 最后一发照常打出去
    check("最后一发能打", a.shots == shots0 + 1)
    check("打空后弹匣为 0", ammo_of(a) == 0)

    m.fire_human(a)                       # 空仓扣扳机 → 自动换弹，不放枪
    check("空仓扣扳机不起火", a.shots == shots0 + 1)
    check("自动开始换弹", a.reload_t == C.RELOAD_TIME, f"{a.reload_t:.2f}")
    check("空仓时不扣弹", ammo_of(a) == 0)


def test_reload_blocks_fire_and_refills():
    m = fresh()
    a = _human_agent(m)
    m._buy(a, "rifle")
    a.mags["rifle"] = 0
    start_reload(a)
    shots0 = a.shots
    m.fire_human(a)
    check("换弹中不能开火", a.shots == shots0)

    # 走完 2s → 弹匣补满
    t = 0.0
    done = False
    while t < C.RELOAD_TIME + 0.1:
        done = tick_reload(a, 1 / 60) or done
        t += 1 / 60
    check(f"换弹 {C.RELOAD_TIME}s 后补满", done and ammo_of(a) == a.weapon.mag,
          f"ammo={ammo_of(a)}")
    check("换弹完成后状态清零", a.reload_t == 0.0)
    m.fire_human(a)
    check("换完弹能继续开火", a.shots == shots0 + 1 and ammo_of(a) == a.weapon.mag - 1)


def test_per_gun_ammo_kept():
    """每把枪各有各的弹匣：切走再切回来，余弹保留。"""
    m = fresh()
    a = _human_agent(m)
    m._buy(a, "rifle")
    for _ in range(5):
        m.fire_human(a)
    check("步枪打了 5 发", ammo_of(a) == MATCH_WEAPONS["rifle"].mag - 5)
    m._buy(a, "awp")                      # 新枪满弹
    check("AWP 满弹", ammo_of(a) == MATCH_WEAPONS["awp"].mag)
    m._select(a, "rifle")                 # 切回步枪
    check("切回步枪余弹保留（25）",
          ammo_of(a) == MATCH_WEAPONS["rifle"].mag - 5, f"{ammo_of(a)}")


def test_score_mode_unlimited():
    """积分赛不受弹药限制：没弹也照常开火、不触发换弹。"""
    m = fresh(mode="score")
    a = _human_agent(m)
    a.weapon = MATCH_WEAPONS["rifle"]
    a.mags = {"rifle": 0}
    shots0 = a.shots
    m.fire_human(a)
    check("积分赛没弹也能开火", a.shots == shots0 + 1)
    check("积分赛不触发换弹", a.reload_t == 0.0)


def test_snapshot_ammo():
    """弹药状态跟着快照走：客户端 HUD 才能显示正确的余弹/换弹进度。"""
    m = fresh()
    a = _human_agent(m)
    m._buy(a, "rifle")
    m.fire_human(a)
    m.fire_human(a)
    start_reload(a)

    snap = m.snapshot()
    entry = [x for x in snap["agents"] if x["controller"] == "human"][0]
    check("快照带弹匣", entry.get("mags", {}).get("rifle")
          == MATCH_WEAPONS["rifle"].mag - 2, f"{entry.get('mags')}")
    check("快照带换弹进度", entry.get("reload_t", 0) > 0, f"{entry.get('reload_t')}")

    m2 = fresh(seed=3)
    m2.apply_snapshot(snap)
    b = m2.agents[entry["id"]]
    check("客户端还原弹匣", ammo_of(b) == MATCH_WEAPONS["rifle"].mag - 2)
    check("客户端还原换弹进度", b.reload_t > 0, f"{b.reload_t:.2f}")


# ---------------------------------------------------------------- AI

def _ai_with_target(m: Match, a):
    """把 a 摆到能看到玩家影子的位置。"""
    tgt = m.player_agent
    tgt.alive = True
    tgt.hp = C.AGENT_HP
    a.x, a.y = tgt.x + 6.0, tgt.y
    a.yaw = math.atan2(tgt.y - a.y, tgt.x - a.x)
    a.target = tgt
    a.react = 0.0
    return tgt


def test_ai_consumes_and_reloads():
    m = fresh()
    m.state = "live"
    m.live_t = 99.0
    a = [x for x in m.agents if x.team == 1][0]
    m._buy(a, "rifle")
    tgt = _ai_with_target(m, a)
    rng = random.Random(3)
    tune = dict(C.AI_PRESETS["normal"])

    start = ammo_of(a)
    for _ in range(180):                  # 3 秒：够打空 30 发并触发自动换弹
        tgt.hp = C.AGENT_HP
        m.player_hp = C.PLAYER_HP
        update_agent(m, a, 1 / 60, rng, tune)
    check("AI 开火消耗弹药", ammo_of(a) < start, f"{start} -> {ammo_of(a)}")
    check("AI 打空自动换弹", a.reload_t > 0 or ammo_of(a) > 0,
          f"reload={a.reload_t:.2f} ammo={ammo_of(a)}")

    # 换弹期间不会再开火（弹药不再减少）
    if a.reload_t > 0:
        frozen = ammo_of(a)
        for _ in range(30):
            tgt.hp = C.AGENT_HP
            m.player_hp = C.PLAYER_HP
            update_agent(m, a, 1 / 60, rng, tune)
            if a.reload_t <= 0:
                break
        check("换弹中弹药保持不变", ammo_of(a) == frozen,
              f"{frozen} -> {ammo_of(a)}")
        check("换弹完成后弹匣补满", ammo_of(a) == MATCH_WEAPONS["rifle"].mag,
              f"{ammo_of(a)}")


def main():
    print("=== 弹药与换弹 ===")
    test_mag_sizes(); print()
    test_fire_consumes(); print()
    test_empty_auto_reload(); print()
    test_reload_blocks_fire_and_refills(); print()
    test_per_gun_ammo_kept(); print()
    test_score_mode_unlimited(); print()
    test_snapshot_ammo(); print()
    test_ai_consumes_and_reloads(); print()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
