"""鼠标视角路由回归：单机 / 主机 / 客户端三种 net_mode 下 MOUSEMOTION 必须都生效。

背景 bug：联机改造时把 MOUSEMOTION 分支写成 `state=="play" and net_mode=="none"`，
主机开局后 state=="play" 但 net_mode=="host"，两个分支都不命中 → 主机鼠标失灵。
"""
import pygame

import config as C
from main import Game

PASS, FAIL = [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append((name, info))
    print(("[ ok ] " if cond else "[FAIL] ") + name + (f"  ({info})" if info else ""))


def _mouse_move(g, dx=60, dy=0):
    pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, rel=(dx, dy)))
    g.handle_events()


def test_host_mouse_look():
    """主机开局后鼠标必须能转视角。"""
    g = Game()
    try:
        g.start_host()
        g._start_host_play()
        check("主机状态就绪", g.state == "play" and g.net_mode == "host")
        yaw0 = g.cam.yaw
        _mouse_move(g, 60, 0)
        check("主机鼠标转动 yaw", abs(g.cam.yaw - yaw0) > 0.01,
              f"dyaw={g.cam.yaw - yaw0:.3f}")
    finally:
        g._close_net()


def test_singleplayer_mouse_look():
    """单机（net_mode=none）鼠标必须仍然能转视角（老路径不回归）。"""
    g = Game()
    try:
        g.start_score()
        yaw0 = g.cam.yaw
        _mouse_move(g, 60, 0)
        check("单机鼠标转动 yaw", abs(g.cam.yaw - yaw0) > 0.01,
              f"dyaw={g.cam.yaw - yaw0:.3f}")
    finally:
        pass


def test_client_accumulates_dyaw():
    """客户端鼠标不该改本地 cam.yaw，而是累积待上行的 yaw 增量。"""
    g = Game()
    try:
        # 不真正联网：手工摆出 client 状态的最小形态
        g.net_mode = "client"
        g.state = "client"
        g._pend_look = 0.0
        yaw0 = g.cam.yaw
        _mouse_move(g, 80, 0)
        check("客户端累积 _pend_look", abs(g._pend_look) > 0.01,
              f"pend={g._pend_look:.3f}")
        check("客户端不改本地 cam.yaw", abs(g.cam.yaw - yaw0) < 1e-9,
              f"dyaw={g.cam.yaw - yaw0:.3f}")
    finally:
        g._close_net()


def main():
    test_host_mouse_look()
    test_singleplayer_mouse_look()
    test_client_accumulates_dyaw()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for name, info in FAIL:
        print(f"  FAIL: {name}  {info}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
