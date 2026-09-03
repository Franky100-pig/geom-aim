"""局域网联机：主机/客户端握手、输入上行、快照下发、分片重组、应用、超时踢人。

全部走 127.0.0.1 回环 UDP，无需显示器。
"""
import json
import math
import socket
import time

import config as C
import engine
from match import Match
from nades import SmokeField
from net import Client, Host

TEST_PORT = 8799

PASS, FAIL = [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append((name, info))


def _wait(host, pred, timeout=1.0):
    """轮询主机直到 pred() 为真（模拟真实游戏循环里 host.poll 每帧调用，
    给 UDP 单包留出从客户端到主机 socket 缓冲区的投递时间）。"""
    end = time.time() + timeout
    while time.time() < end:
        host.poll()
        if pred():
            return True
        time.sleep(0.005)
    host.poll()
    return pred()


def _fresh_match(seed=None):
    arena_rng = __import__("random").Random(seed) if seed is not None else __import__("random").Random()
    g = engine.build_arena(C.SCORE_MAP_TILES_X, C.SCORE_MAP_TILES_Y,
                           C.SCORE_MAP_ROOM_W, C.SCORE_MAP_ROOM_H,
                           rng=arena_rng, cover=True)
    m = Match(g, __import__("random").Random(), "normal", SmokeField(), mode="score")
    return g, m, seed


class _Pump:
    """后台线程：在客户端握手/通信期间持续 poll 主机，模拟真实游戏循环。"""

    def __init__(self, host):
        self.host = host
        self._run = True
        self._t = __import__("threading").Thread(target=self._loop, daemon=True)

    def _loop(self):
        while self._run:
            self.host.poll()
            time.sleep(0.01)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._run = False
        self._t.join(timeout=1.0)


def test_join_and_input():
    g, m, seed = _fresh_match(seed=12345)
    host = Host(g, m, TEST_PORT, seed=seed, cover=True)
    try:
        before = m.human_count
        cli = Client("127.0.0.1", name="Tester", port=TEST_PORT)
        with _Pump(host):
            welcome = cli.connect(timeout=3.0)
        check("客户端拿到 welcome", welcome is not None and welcome.get("t") == "welcome")
        if welcome:
            check("welcome 含地图种子", isinstance(welcome.get("seed"), int))
            # 客户端按种子 + 尺寸确定性重建地图，应与主机一致
            cg = engine.build_arena(welcome["tiles_x"], welcome["tiles_y"],
                                    welcome["room_w"], welcome["room_h"],
                                    rng=__import__("random").Random(welcome["seed"]),
                                    cover=welcome.get("cover", True))
            check("客户端地图与主机同形", cg.g == g.g,
                  f"h={len(g.g)} c={len(cg.g)}")
            check("welcome 含本机 uid", isinstance(welcome.get("uid"), int)
                  and welcome["uid"] >= 0, f"uid={welcome.get('uid')}")
            cm = Match(cg, __import__("random").Random(), "normal",
                       SmokeField(), mode="score")
            check("加入后主机真人 slot +1", m.human_count == before + 1,
                  f"{before} -> {m.human_count}")

            new_agent = m.agents[-1]
            x0 = new_agent.x
            cli.send_input(dict(mvx=1.0, mvy=0.0, crouch=False, jump=False,
                                fire=False, weapon="rifle", smoke=False, dyaw=0.0))
            _wait(host, lambda: new_agent in m.human_inputs)
            m.update(0.05)
            check("主机收到输入并驱动真人移动", abs(new_agent.x - x0) > 0.01,
                  f"dx={new_agent.x - x0:.3f}")

            host.broadcast(m.snapshot())
            for _ in range(10):
                cli.pump()
                if cli.snap is not None:
                    break
                time.sleep(0.005)
            check("客户端收到快照", cli.snap is not None)
            if cli.snap is not None:
                cm.apply_snapshot(cli.snap)
                check("快照应用后客户端有 agent", len(cm.agents) >= 2,
                      f"n={len(cm.agents)}")
                check("客户端本地玩家存在", cm.player_agent is not None)
                check("快照分数与主机一致", cm.team_kills == m.team_kills)
                own = [a for a in cm.agents if getattr(a, "uid", None) == welcome["uid"]]
                check("客户端能按 uid 定位自己的 Agent", len(own) == 1,
                      f"uid={welcome['uid']} n={len(own)}")

            yaw0 = new_agent.yaw
            for _ in range(5):
                cli.send_input(dict(mvx=0, mvy=0, crouch=False, jump=False,
                                    fire=False, weapon="rifle", smoke=False,
                                    dyaw=0.1))
                time.sleep(0.02)   # 等 _Pump 把输入收进 human_inputs
                host.poll()
                m.update(0.05)
            check("连续 dyaw 改变真人朝向", abs(new_agent.yaw - yaw0) > 0.3,
                  f"dyaw={new_agent.yaw - yaw0:.3f}")
        cli.leave()
    finally:
        host.close()


def test_room_full():
    g, m, _s = _fresh_match()
    host = Host(g, m, TEST_PORT + 1)
    try:
        m.human_count = C.NET_MAX_HUMANS
        cli = Client("127.0.0.1", name="X", port=TEST_PORT + 1)
        with _Pump(host):
            welcome = cli.connect(timeout=2.0)
        check("房间满时拒绝加入", welcome is None, f"welcome={welcome}")
        cli.leave()
    finally:
        host.close()


def test_snapshot_smoke_roundtrip():
    g, m, _s = _fresh_match()
    m.smokes.plant(20.0, 20.0, radius=1.4)
    snap = m.snapshot()
    data = __import__("json").loads(__import__("json").dumps(snap))  # 模拟网络往返
    m2 = _fresh_match()[1]
    m2.apply_snapshot(data)
    check("烟团快照往返后保留", len(m2.smokes.grenades) == 1,
          f"n={len(m2.smokes.grenades)}")
    g2 = m2.smokes.grenades[0]
    check("烟团半径正确", abs(g2._r - 1.4) < 1e-6, f"r={g2._r}")


def test_timeout_kick():
    g, m, _s = _fresh_match()
    host = Host(g, m, TEST_PORT + 2)
    try:
        cli = Client("127.0.0.1", name="Z", port=TEST_PORT + 2)
        with _Pump(host):
            cli.connect(timeout=2.0)
        n0 = m.human_count
        # 把该客户端的最后活跃时间拨到很久以前，poll 应踢掉
        for info in host.clients.values():
            info["last"] = time.time() - (C.NET_TIMEOUT + 1.0)
        host.poll()
        check("超时客户端被踢出", m.human_count == n0 - 1,
              f"{n0} -> {m.human_count}")
        cli.leave()
    finally:
        host.close()


if __name__ == "__main__":
    test_join_and_input()
    test_room_full()
    test_snapshot_smoke_roundtrip()
    test_timeout_kick()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for n, i in FAIL:
        print("  FAIL:", n, i)
    raise SystemExit(1 if FAIL else 0)
