"""Q 上一把（CS2 lastinv）与鼠标滚轮切枪（CS2 默认）的单元测试。

直接跑：  SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy PYTHONPATH=. \\
            python3 -m pytest tests/test_lastinv_wheel.py -q
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402
import config as C  # noqa: E402
import engine  # noqa: E402
import main  # noqa: E402
from match import Match  # noqa: E402

G = engine.build_arena(C.ARENA_TILES_X, C.ARENA_TILES_Y, C.ARENA_ROOM_W, C.ARENA_ROOM_H)

import random as _random  # noqa: E402


def _mk() -> Match:
    return Match(G, _random.Random(7), 0, None, mode="match")


def test_lastinv_toggles_between_two_guns():
    m = _mk()
    pa = m.player_agent
    assert pa.last_weapon_key == "knife"          # 回合开始默认刀
    assert m.player_buy("pistol") is True
    assert pa.weapon.key == "pistol"
    assert pa.last_weapon_key == "knife"          # 切到手枪后，上一把记成刀
    # Q 切回刀
    assert m.player_lastinv() is True
    assert pa.weapon.key == "knife"
    assert pa.last_weapon_key == "pistol"         # 再切回去，上一把变成手枪
    # 还没买第二把时再 Q 又切回手枪
    assert m.player_lastinv() is True
    assert pa.weapon.key == "pistol"


def test_lastinv_noop_when_nothing_to_return():
    m = _mk()
    pa = m.player_agent
    pa.last_weapon_key = None
    assert m.player_lastinv() is False            # 没切过枪，Q 不动


def test_cycle_direction_prev_next():
    m = _mk()
    pa = m.player_agent
    assert pa.loadout == ["knife"]                 # 回合开始只有刀
    assert m.player_buy("pistol") is True          # loadout: [knife, pistol]
    assert pa.weapon.key == "pistol"
    # 上一把（-1）→ 刀
    assert m.player_cycle_dir(-1) is True
    assert pa.weapon.key == "knife"
    # 下一把（+1）→ 手枪
    assert m.player_cycle_dir(1) is True
    assert pa.weapon.key == "pistol"
    # 再下一把（+1）绕回 → 刀
    assert m.player_cycle_dir(1) is True
    assert pa.weapon.key == "knife"


def test_host_q_key_swaps_to_last_weapon():
    g = main.Game()
    g.start_match()
    assert g.state == "play"
    assert g.match.state == "prep"
    # 买一把手枪（确定买得起）
    g.on_key(pygame.K_1)               # 1 = pistol
    assert g.match.player_agent.weapon.key == "pistol"
    # 按 Q 切回初始刀
    g.on_key(pygame.K_q)
    assert g.match.player_agent.weapon.key == "knife"
    assert g.player.weapon.key == "knife"   # 同步到 Player


def test_host_wheel_cycles_weapons():
    g = main.Game()
    g.start_match()
    g.on_key(pygame.K_1)               # 买手枪：loadout=[knife, pistol]
    assert g.match.player_agent.weapon.key == "pistol"
    # 清掉无头模式启动时 pygame 产生的杂散事件，避免误触状态
    pygame.event.clear()
    # 下滚（ev.y<0 → dir +1）→ 切到下一把（knife）
    pygame.event.post(pygame.event.Event(pygame.MOUSEWHEEL, y=-1))
    g.handle_events()
    assert g.match.player_agent.weapon.key == "knife"
    # 上滚（ev.y>0 → dir -1）→ 切回上一把（pistol）
    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.MOUSEWHEEL, y=1))
    g.handle_events()
    assert g.match.player_agent.weapon.key == "pistol"


def test_b_toggles_buy_menu():
    g = main.Game()
    g.start_match()
    assert g.buy_menu_open is True
    g.on_key(pygame.K_b)
    assert g.buy_menu_open is False
    g.on_key(pygame.K_b)
    assert g.buy_menu_open is True
