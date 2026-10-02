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
    # 没开火 -> accuracy() 返回 None，不该污染均值
    rows = [_s(shots=0, hits=0), _s(shots=0, hits=0),
            _s(hits=100, shots=100), _s(hits=100, shots=100)]
    t = analytics.trend(rows, n=2, key="accuracy")
    check("trend 跳过 None 指标", abs(t["recent"] - 1.0) < 1e-9, str(t["recent"]))
    check("trend 只用有效值算 prev", abs(t["prev"] - 1.0) < 1e-9, str(t["prev"]))


if __name__ == "__main__":
    test_trend_newest_vs_previous()
    test_trend_returns_none_when_no_history()
    test_trend_ignores_undefined_metrics()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        raise SystemExit(1)
