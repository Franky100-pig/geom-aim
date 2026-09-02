"""H 键返回主菜单的回归测试（无头运行，不需要显示器）。

运行：
  SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy PYTHONPATH=. \
    /usr/local/bin/python3 tests/test_title_return.py
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402
import config as C  # noqa: E402
import main  # noqa: E402


def make_game():
    g = main.Game()
    return g


def test_practice_to_title():
    g = make_game()
    g.start_practice("botz")
    assert g.state == "play", "练习应当进入 play"
    assert g.match is None
    g.on_key(pygame.K_h)
    assert g.state == "title", "H 后应回到标题"
    assert g.match is None
    # 标题背景用的是练习大地图，必须重建回来（不是对战小地图）
    assert g.gmap.tiles_x == C.ARENA_TILES_X, "应重建练习大地图"
    assert g.smoke_left == C.SMOKE_PRACTICE_MAX
    assert not g.player.firing
    print("  [ok] 练习 -> H -> 标题")


def test_match_to_title():
    g = make_game()
    g.start_match()
    assert g.state == "play", "对战应当进入 play"
    assert g.match is not None
    assert g.gmap.tiles_x == C.MATCH_TILES_X, "对战用小地图"
    g.on_key(pygame.K_h)
    assert g.state == "title", "H 后应回到标题"
    assert g.match is None
    assert g.gmap.tiles_x == C.ARENA_TILES_X, "应重建练习大地图"
    print("  [ok] 对战 -> H -> 标题")


def test_title_then_start_match():
    # 回标题后应当能直接再开对战，不必重启程序
    g = make_game()
    g.start_match()
    g.on_key(pygame.K_h)
    assert g.state == "title"
    g.on_key(pygame.K_2)           # 标题界面 2 = 对战
    assert g.state == "play", "回标题后按 2 应能再开对战"
    assert g.match is not None
    print("  [ok] 回标题后按 2 再开对战")


def test_menu_state_h_returns_title():
    # ESC 暂停菜单里按 H 也应回标题
    g = make_game()
    g.start_practice("botz")
    g.on_key(pygame.K_ESCAPE)
    assert g.state == "menu"
    g.on_key(pygame.K_h)
    assert g.state == "title", "菜单里 H 也应回标题"
    print("  [ok] 菜单 -> H -> 标题")


if __name__ == "__main__":
    test_practice_to_title()
    test_match_to_title()
    test_title_then_start_match()
    test_menu_state_h_returns_title()
    print("PASS: H 返回主菜单 全部通过")
