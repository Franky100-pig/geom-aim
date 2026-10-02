"""TDD 测试：analytics.py 战绩分析层（Phase 1.5，纯本地）。

直接跑：  python3 tests/test_analytics.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stats  # noqa: E402
from stats import Session  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def _s(mode="botz", shots=100, hits=50, headshots=10, kills=10,
       deaths=5, score=300, dur=60.0, at=0.0):
    return Session(mode=mode, shots=shots, hits=hits, headshots=headshots,
                   kills=kills, deaths=deaths, score=score,
                   duration_s=dur, created_at=at)


def test_trend_newest_vs_previous():
    import analytics
    rows = [_s(hits=100, shots=100), _s(hits=100, shots=100),
            _s(hits=20, shots=100), _s(hits=20, shots=100)]
    t = analytics.trend(rows, n=2, key="accuracy")
    check("trend recent 取最近 n 局平均", abs(t["recent"] - 1.0) < 1e-9, str(t["recent"]))
    check("trend prev 取前 n 局平均", abs(t["prev"] - 0.2) < 1e-9, str(t["prev"]))
    check("trend delta = recent - prev", abs(t["delta"] - 0.8) < 1e-9, str(t["delta"]))


def test_trend_returns_none_when_no_history():
    import analytics
    rows = [_s(hits=50, shots=100)]
    t = analytics.trend(rows, n=5, key="accuracy")
    check("只有一局时 prev 为 None", t["prev"] is None, str(t["prev"]))
    check("prev 为 None 时 delta 为 None", t["delta"] is None, str(t["delta"]))


def test_trend_ignores_undefined_metrics():
    import analytics
    # 没开火 -> accuracy() 返回 None。窗口内混合 None 与有效值时，
    # None 应被跳过（而不是当成 0 拉低均值）。
    rows = [_s(shots=0, hits=0), _s(hits=100, shots=100),
            _s(hits=20, shots=100), _s(hits=40, shots=100)]
    t = analytics.trend(rows, n=2, key="accuracy")
    check("trend 跳过 None 只算有效值", abs(t["recent"] - 1.0) < 1e-9,
          str(t["recent"]))
    check("prev 按普通均值算", abs(t["prev"] - 0.3) < 1e-9, str(t["prev"]))


def test_trend_window_all_undefined():
    import analytics
    # 最近 n 局全都「没开火」-> 该窗口没有可算的值，返回 None（而不是 0）
    rows = [_s(shots=0, hits=0), _s(shots=0, hits=0),
            _s(hits=20, shots=100), _s(hits=40, shots=100)]
    t = analytics.trend(rows, n=2, key="accuracy")
    check("窗口内全是 None 时 recent 为 None", t["recent"] is None, str(t["recent"]))
    check("prev 仍按有效值算", abs(t["prev"] - 0.3) < 1e-9, str(t["prev"]))
    check("recent 为 None 时 delta 也为 None", t["delta"] is None, str(t["delta"]))


def test_moving_average_basic():
    import analytics
    ma = analytics.moving_average([1, 2, 3, 4], window=3)
    check("ma 长度不变", len(ma) == 4, str(ma))
    check("ma[0] 只有一个样本", ma[0] == 1.0, str(ma[0]))
    check("ma[1] 前两个均值", abs(ma[1] - 1.5) < 1e-9, str(ma[1]))
    check("ma[2] 窗口满", abs(ma[2] - 2.0) < 1e-9, str(ma[2]))
    check("ma[3] 滑动", abs(ma[3] - 3.0) < 1e-9, str(ma[3]))


def test_moving_average_skips_none():
    import analytics
    ma = analytics.moving_average([None, 4, 6], window=2)
    check("段内全是 None -> None（不是 0）", ma[0] is None, str(ma))
    check("None 被跳过不拉低均值", ma[1] == 4.0, str(ma))
    check("None 之后的段正常", ma[2] == 5.0, str(ma))


def test_moving_average_window_one():
    import analytics
    ma = analytics.moving_average([2, None, 4], window=1)
    check("window=1 原样返回", ma == [2.0, None, 4.0], str(ma))


if __name__ == "__main__":
    test_trend_newest_vs_previous()
    test_trend_returns_none_when_no_history()
    test_trend_ignores_undefined_metrics()
    test_trend_window_all_undefined()
    test_moving_average_basic()
    test_moving_average_skips_none()
    test_moving_average_window_one()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        raise SystemExit(1)
