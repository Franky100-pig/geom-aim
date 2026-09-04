"""联机功能审计修复的回归测试。

覆盖：
1. 真人加入顶替 AI（保持 5v5）
2. 每个 Agent 独立战绩（kills/deaths/shots/hits）+ 快照往返
3. 客户端右键开镜 / 阵亡强制收镜
4. 客户端断线超时回标题
5. 主机积分赛烟雾弹与 AI/客户端一致（开局/重生 1 颗）
6. 联机主机按 R 不再重开（房间不会被搞乱）
"""
import time

import pygame

import config as C
import engine
from main import Game
from match import Match
from nades import SmokeField

PASS, FAIL = [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append((name, info))
    print(("[ ok ] " if cond else "[FAIL] ") + name + (f"  ({info})" if info else ""))


def _match():
    g = engine.build_arena(C.SCORE_MAP_TILES_X, C.SCORE_MAP_TILES_Y,
                           C.SCORE_MAP_ROOM_W, C.SCORE_MAP_ROOM_H,
                           rng=__import__("random").Random(7), cover=True)
    return Match(g, __import__("random").Random(), "normal", SmokeField(),
                 mode="score")


def test_add_human_replaces_ai():
    """真人加入应顶替本队 AI，队伍人数保持 5v5。"""
    m = _match()
    n0 = len(m.agents)
    m.add_human_agent(0, "A")
    m.add_human_agent(0, "B")
    t0 = sum(1 for a in m.agents if a.team == 0)
    t1 = sum(1 for a in m.agents if a.team == 1)
    humans = sum(1 for a in m.agents if a.controller == "human")
    check("队伍保持 5v5", t0 == 5 and t1 == 5 and len(m.agents) == n0,
          f"t0={t0} t1={t1} n={len(m.agents)}/{n0}")
    check("真人数量为 2", humans == 2, f"humans={humans}")


def test_per_agent_stats():
    """击杀/阵亡记在 shooter/tgt 的 Agent 身上，而不只是 match.stats。"""
    m = _match()
    shooter = next(a for a in m.agents if a.team == 1 and a.controller == "ai")
    tgt = next(a for a in m.agents if a.team == 0 and a.controller == "ai")
    tgt.invuln = 0.0
    for _ in range(200):
        if not tgt.alive:
            break
        m.apply_damage(shooter, tgt, head=False)
    check("击杀记到 shooter.kills", shooter.kills == 1, f"kills={shooter.kills}")
    check("阵亡记到 tgt.deaths", tgt.deaths == 1, f"deaths={tgt.deaths}")


def test_snapshot_stats_roundtrip():
    """快照应携带每人的战绩与烟雾弹数，客户端 apply_snapshot 能还原。"""
    m = _match()
    h = m.add_human_agent(0, "A")
    h.kills, h.deaths, h.shots, h.hits = 3, 1, 10, 4
    h.smoke_charges = 1
    m2 = _match()
    m2.apply_snapshot(m.snapshot())
    h2 = next(a for a in m2.agents if a.controller == "human")
    check("快照往返战绩一致",
          (h2.kills, h2.deaths, h2.shots, h2.hits, h2.smoke_charges)
          == (3, 1, 10, 4, 1),
          f"k={h2.kills} d={h2.deaths} s={h2.shots} h={h2.hits} "
          f"smoke={h2.smoke_charges}")


def test_client_ads_toggle():
    """客户端右键本地切换开镜。"""
    g = Game()
    try:
        g.net_mode = "client"
        g.state = "client"
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=3, pos=(0, 0)))
        g.handle_events()
        check("客户端右键开镜", g.player.ads is True)
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=3, pos=(0, 0)))
        g.handle_events()
        check("再按一次收镜", g.player.ads is False)
    finally:
        g._close_net()


def test_client_disconnect_timeout():
    """超过 NET_TIMEOUT 收不到主机包 → 回标题并提示。"""
    g = Game()
    try:
        class FakeClient:
            def __init__(self):
                self.last_recv = time.time() - (C.NET_TIMEOUT + 1.0)
                self.snap = None

            def pump(self):
                pass

            def send_input(self, inp):
                pass

        g.net_mode = "client"
        g.state = "client"
        g.client = FakeClient()
        g._update_client(0.05)
        check("断线回标题", g.state == "title")
        check("显示断线提示", "断开" in g.connect_error,
              f"err={g.connect_error!r}")
    finally:
        g._close_net()


def test_score_smoke_for_host_player():
    """积分赛：主机玩家开局有 1 颗烟，重生后也补回 1 颗。"""
    g = Game()
    try:
        g.start_score()
        m = g.match
        check("开局 1 颗烟", g.smoke_left == C.SMOKE_AI_SCORE_CHARGES,
              f"left={g.smoke_left}")
        # 打死玩家，等重生
        shooter = next(a for a in m.agents if a.team == 1)
        m.player_agent.invuln = 0.0
        for _ in range(200):
            if m.player_dead:
                break
            m.apply_damage(shooter, m.player_agent, head=False)
        g.smoke_left = 0
        for _ in range(int((C.SCORE_RESPAWN_DELAY + 1.0) / 0.05)):
            g._update_score_match(0.05)
            if not m.player_dead:
                break
        check("重生补回 1 颗烟", g.smoke_left >= 1, f"left={g.smoke_left}")
    finally:
        pass


def test_no_r_restart_on_host():
    """联机主机比赛结束后按 R 不重开（match 对象不变）。"""
    g = Game()
    try:
        g.start_host()
        g._start_host_play()
        m = g.match
        m.state = "match_end"
        g.on_key(pygame.K_r)
        check("主机 R 不重开", g.match is m)
    finally:
        g._close_net()


def main():
    test_add_human_replaces_ai()
    test_per_agent_stats()
    test_snapshot_stats_roundtrip()
    test_client_ads_toggle()
    test_client_disconnect_timeout()
    test_score_smoke_for_host_player()
    test_no_r_restart_on_host()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for name, info in FAIL:
        print(f"  FAIL: {name}  {info}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
