"""战绩分析层（Phase 1.5，纯本地）。

职责
----
把 `stats.py` 里已有的 Session 记录算出「人能读懂的结论」：
趋势变化、分模式汇总、最佳/最差局、达标连胜、CSV 导出。

设计约束
--------
- **纯本地**：不联网、不碰账号系统。账号系统要等用户数 ≥20 才动（见
  docs/ACCOUNT_SYSTEM_PLAN.md §1），这里一块服务端的东西都不碰。
- **纯函数**：只读 Session 列表，不碰 SQLite、不发 IO，所以能直接单测。
- 所有「没有定义」的指标一律返回 None 交给 UI 显示「—」，不猜数。
"""

from __future__ import annotations

from typing import Optional, Sequence

from stats import Session, aggregate  # noqa: F401  (aggregate 供调用方复用)


def _mean(vals: Sequence[Optional[float]]) -> Optional[float]:
    """对可比较数值取均值；全空或含 None 时忽略 None。"""
    real = [v for v in vals if v is not None]
    return (sum(real) / len(real)) if real else None


def trend(rows: Sequence[Session], n: int = 5,
          key: str = "accuracy") -> dict:
    """最近 n 局 vs 前 n 局的变化。

    rows 按「最新在前」排列（stats.LocalStatsStore.recent 已经是这个顺序）。
    返回 ``{"recent": ..., "prev": ..., "delta": ...}``，None 表示样本不足。
    """
    vals = [getattr(r, key)() for r in rows]
    recent = _mean(vals[:n])
    prev = _mean(vals[n:2 * n])
    delta = None if (recent is None or prev is None) else recent - prev
    return {"recent": recent, "prev": prev, "delta": delta}


def moving_average(values: Sequence[Optional[float]],
                   window: int) -> list[Optional[float]]:
    """滑动平均，输出长度与输入一致（头部样本不足时用已有数据算）。

    与 trend() 同一套语义：None 跳过不拉低均值；段内全是 None 则该点为 None。
    window <= 1 时原样返回（转 float）。
    """
    if window <= 1:
        return [float(v) if v is not None else None for v in values]
    out: list[Optional[float]] = []
    for i in range(len(values)):
        lo = max(0, i - window + 1)
        out.append(_mean(values[lo:i + 1]))
    return out


def per_mode_summary(rows: Sequence[Session]) -> list[dict]:
    """按模式分组汇总（复用 stats.aggregate），按局数降序。

    返回字段：mode / sessions / accuracy / headshot_rate / kd / score。
    """
    groups: dict[str, list[Session]] = {}
    for r in rows:
        groups.setdefault(r.mode, []).append(r)
    out = []
    for mode, rs in groups.items():
        a = aggregate(rs)
        out.append({"mode": mode, "sessions": a["sessions"],
                    "accuracy": a["accuracy"],
                    "headshot_rate": a["headshot_rate"],
                    "kd": a["kd"], "score": a["score"]})
    out.sort(key=lambda d: d["sessions"], reverse=True)
    return out


def best_worst(rows: Sequence[Session],
               key: str = "accuracy") -> tuple[Optional[Session],
                                               Optional[Session]]:
    """按某派生指标选最佳/最差的一局（没开火的局不参与）。

    返回 ``(best, worst)``；没有任何可比较样本时返回 ``(None, None)``。
    """
    pairs = [(r, getattr(r, key)()) for r in rows]
    valid = [(r, v) for r, v in pairs if v is not None]
    if not valid:
        return (None, None)
    best = max(valid, key=lambda p: p[1])[0]
    worst = min(valid, key=lambda p: p[1])[0]
    return (best, worst)


def streaks(rows: Sequence[Session], threshold: float = 0.5) -> dict:
    """命中率达标连胜统计。

    rows 按「最新在前」。``current`` 从最新局往回数连续达标的局数；
    ``best`` 是任意位置出现过的最长连胜。没开火的局（accuracy 为 None）
    视为不达标：中断 current，也不延续 best。
    """
    best = 0
    run = 0
    for r in rows:
        acc = r.accuracy()
        if acc is not None and acc >= threshold:
            run += 1
            best = max(best, run)
        else:
            run = 0

    # current 是「从最新局开始的prefix 连胜」；上面的 run 是遍历到最旧一局
    # 时尾部的连胜，二者不是一回事，必须单独数。
    current = 0
    for r in rows:
        acc = r.accuracy()
        if acc is not None and acc >= threshold:
            current += 1
        else:
            break
    return {"current": current, "best": best, "sessions": len(rows)}
