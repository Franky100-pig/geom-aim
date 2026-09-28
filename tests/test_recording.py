"""回归测试：战绩落库 hook（练习退出 + 对战结束）。

直接跑：  python3 tests/test_recording.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
from stats import LocalStatsStore, Session  # noqa: E402

PASS, FAIL = [], []


def _fresh_db() -> str:
    """每个测试用独立临时库，避免互相串数据（改 env 后构造 Game）。"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="geom_aim_rec_")
    os.close(fd)
    os.unlink(path)
    os.environ["GEOM_AIM_STATS_DB"] = path
    return path


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def _store():
    return LocalStatsStore(os.environ["GEOM_AIM_STATS_DB"])


def test_practice_session_recorded_on_exit():
    """离开练习模式（to_title）应落库一条练习战绩，字段对齐。"""
    _fresh_db()
    g = main.Game()
    g.start_practice("botz")
    g.shots = 200
    g.hit_count = 140
    g.headshots = 30
    g.score = 777
    g.to_title()

    rows = g.stats_store.recent()
    check("退出练习后落库 1 条", len(rows) == 1, str(len(rows)))
    if rows:
        r = rows[0]
        check("mode=botz", r.mode == "botz", r.mode)
        check("shots=200", r.shots == 200, str(r.shots))
        check("hits=140", r.hits == 140, str(r.hits))
        check("headshots=30", r.headshots == 30, str(r.headshots))
        check("score=777", r.score == 777, str(r.score))
        check("练习无击杀/死亡", r.kills == 0 and r.deaths == 0)
        check("命中率=0.7", abs(r.accuracy() - 0.7) < 1e-9, str(r.accuracy()))


def test_practice_no_record_when_untouched():
    """刚进练习就退出（没开过火）不应留空记录。"""
    _fresh_db()
    g = main.Game()
    g.start_practice("reflex")
    g.to_title()
    check("空练习不落库", len(g.stats_store.recent()) == 0,
          str(len(g.stats_store.recent())))


def test_match_session_record_once():
    """对战结束那一帧落库，且只落一次（不会每帧重复写）。"""
    _fresh_db()
    g = main.Game()
    g.start_match()
    m = g.match
    # 模拟一场打满的对战战绩
    m.stats["shots"] = 120
    m.stats["hits"] = 60
    m.stats["headshots"] = 12
    m.stats["kills"] = 18
    m.stats["deaths"] = 9
    m.state = "match_end"          # match_over == True

    g._maybe_record_match(m)
    g._maybe_record_match(m)        # 第二帧：不应再写
    g._maybe_record_match(m)

    rows = g.stats_store.recent()
    check("对战只落库 1 条", len(rows) == 1, str(len(rows)))
    if rows:
        r = rows[0]
        check("mode=match", r.mode == "match", r.mode)
        check("kills=18/deaths=9", (r.kills, r.deaths) == (18, 9))
        check("KD=2.0", abs(r.kd() - 2.0) < 1e-9, str(r.kd()))


def test_match_session_not_recorded_before_end():
    """对战没结束（还在打）时不应落库。"""
    _fresh_db()
    g = main.Game()
    g.start_match()
    m = g.match
    m.stats["shots"] = 50
    g._maybe_record_match(m)        # match_over 仍为 False
    check("未结束不落库", len(g.stats_store.recent()) == 0,
          str(len(g.stats_store.recent())))


def run_tests():
    print("=== 战绩落库 hook 回归 ===")
    test_practice_session_recorded_on_exit(); print()
    test_practice_no_record_when_untouched(); print()
    test_match_session_record_once(); print()
    test_match_session_not_recorded_before_end(); print()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
