"""TDD 测试：stats.py 本地战绩数据层。

直接跑：  python3 tests/test_stats.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stats  # noqa: E402
from stats import LocalStatsStore, Session, aggregate  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def _tmp_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return LocalStatsStore(path)


def test_record_then_recent():
    s = _tmp_store()
    s.record(Session(mode="botz", shots=100, hits=70, headshots=10,
                    score=420, duration_s=60.0))
    rows = s.recent()
    check("落库后 recent 拿到 1 条", len(rows) == 1, str(len(rows)))
    r = rows[0]
    check("mode 正确", r.mode == "botz", r.mode)
    check("数值正确", (r.shots, r.hits, r.headshots, r.score) == (100, 70, 10, 420))


def test_recent_is_newest_first():
    s = _tmp_store()
    s.record(Session(mode="a", shots=1, created_at=100.0))
    s.record(Session(mode="b", shots=1, created_at=200.0))
    s.record(Session(mode="c", shots=1, created_at=150.0))
    modes = [r.mode for r in s.recent()]
    check("recent 按时间倒序", modes == ["b", "c", "a"], str(modes))


def test_by_mode_filters():
    s = _tmp_store()
    s.record(Session(mode="botz", shots=10))
    s.record(Session(mode="match", shots=20))
    s.record(Session(mode="botz", shots=30))
    botz = s.by_mode("botz")
    check("by_mode 只返回该模式", {r.mode for r in botz} == {"botz"}
          and len(botz) == 2, str([r.mode for r in botz]))


def test_accuracy_none_when_no_shots():
    s0 = Session(mode="x", shots=0, hits=0)
    check("零开火时命中率为 None", s0.accuracy() is None)
    check("零开火时爆头率为 None", s0.headshot_rate() is None)
    s1 = Session(mode="x", shots=100, hits=50, headshots=20)
    check("命中率=0.5", abs(s1.accuracy() - 0.5) < 1e-9, str(s1.accuracy()))
    check("爆头率=0.2", abs(s1.headshot_rate() - 0.2) < 1e-9, str(s1.headshot_rate()))


def test_kd_rules():
    no_death = Session(mode="m", kills=5, deaths=0)
    check("零死亡 KD=None（不是除零）", no_death.kd() is None)
    with_death = Session(mode="m", kills=8, deaths=2)
    check("KD=4.0", abs(with_death.kd() - 4.0) < 1e-9, str(with_death.kd()))


def test_aggregate_totals_and_rates():
    rows = [
        Session(mode="botz", shots=100, hits=80, headshots=20, score=500),
        Session(mode="match", shots=50, hits=25, headshots=5, kills=9, deaths=3),
    ]
    agg = aggregate(rows)
    check("汇总局数=2", agg["sessions"] == 2)
    check("汇总开火=150", agg["shots"] == 150)
    check("汇总命中=105", agg["hits"] == 105)
    check("汇总爆头=25", agg["headshots"] == 25)
    check("汇总击杀=9", agg["kills"] == 9)
    check("汇总死亡=3", agg["deaths"] == 3)
    check("总命中率=0.7", abs(agg["accuracy"] - 0.7) < 1e-9, str(agg["accuracy"]))
    check("总爆头率=1/6", abs(agg["headshot_rate"] - 25 / 150) < 1e-9)
    check("总KD=3.0", abs(agg["kd"] - 3.0) < 1e-9, str(agg["kd"]))


def test_aggregate_empty():
    agg = aggregate([])
    check("空记录 sessions=0", agg["sessions"] == 0)
    check("空记录 accuracy=None", agg["accuracy"] is None)
    check("空记录 kd=None", agg["kd"] is None)


def run_tests():
    print("=== stats.py 本地战绩层 回归 ===")
    test_record_then_recent(); print()
    test_recent_is_newest_first(); print()
    test_by_mode_filters(); print()
    test_accuracy_none_when_no_shots(); print()
    test_kd_rules(); print()
    test_aggregate_totals_and_rates(); print()
    test_aggregate_empty(); print()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
