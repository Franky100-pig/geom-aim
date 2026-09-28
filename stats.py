"""本地战绩数据层（Phase 1：SQLite，离线优先）。

设计目标
--------
- 极简、离线优先：每局 / 每次练习结束先落本地 SQLite，立刻能看历史，永不依赖网络。
- 抽象成 StatsStore 接口；本地实现是 LocalStatsStore。以后接云（Supabase 之类）
  只需加一个子类实现同样的接口，业务代码（main.py 的落库调用）一行都不用改。
- 只存「匿名战绩」：mode + 数值 + 时间，不碰任何个人信息（合规友好）。

战绩字段（与用户选定的需求对齐：命中率 / 爆头率 / 击杀死亡）
-----------------------------------------------------------
- mode        模式：botz / reflex / tracking / peek（练习）或 match / score（对战）
- shots       开火数（练习与对战都记；为算命中率）
- hits        命中数
- headshots   爆头数
- kills       击杀（仅对战有，练习为 0）
- deaths      死亡（仅对战有，练习为 0）
- score       练习得分（对战为 0）
- duration_s  本局/本次练习时长（秒）
- created_at  记录时间（epoch 秒）
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class Session:
    """一条战绩记录。"""

    mode: str
    shots: int = 0
    hits: int = 0
    headshots: int = 0
    kills: int = 0
    deaths: int = 0
    score: int = 0
    duration_s: float = 0.0
    created_at: float = 0.0

    # —— 派生指标：没有开火就不算（返回 None，UI 显示「—」）——
    def accuracy(self) -> Optional[float]:
        return self.hits / self.shots if self.shots > 0 else None

    def headshot_rate(self) -> Optional[float]:
        return self.headshots / self.shots if self.shots > 0 else None

    def kd(self) -> Optional[float]:
        # 死亡为 0 时 KD 没有定义（避免把"没死过"误显成击杀数），UI 显示「—」
        return self.kills / self.deaths if self.deaths > 0 else None


class StatsStore:
    """战绩存取接口（本地与云端共用）。"""

    def record(self, s: Session) -> None:
        raise NotImplementedError

    def recent(self, limit: int = 50) -> list[Session]:
        raise NotImplementedError

    def by_mode(self, mode: str) -> list[Session]:
        raise NotImplementedError

    def all(self) -> list[Session]:
        raise NotImplementedError


class LocalStatsStore(StatsStore):
    """SQLite 实现。路径可用环境变量 GEOM_AIM_STATS_DB 覆盖（测试用临时库）。"""

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.environ.get("GEOM_AIM_STATS_DB") or (
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "geom_aim_stats.db")
        )
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS sessions (
                       id          INTEGER PRIMARY KEY AUTOINCREMENT,
                       mode        TEXT NOT NULL,
                       shots       INTEGER NOT NULL DEFAULT 0,
                       hits        INTEGER NOT NULL DEFAULT 0,
                       headshots   INTEGER NOT NULL DEFAULT 0,
                       kills       INTEGER NOT NULL DEFAULT 0,
                       deaths      INTEGER NOT NULL DEFAULT 0,
                       score       INTEGER NOT NULL DEFAULT 0,
                       duration_s  REAL NOT NULL DEFAULT 0,
                       created_at  REAL NOT NULL DEFAULT 0
                   )"""
            )

    def record(self, s: Session) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO sessions
                       (mode, shots, hits, headshots, kills, deaths,
                        score, duration_s, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (s.mode, s.shots, s.hits, s.headshots, s.kills, s.deaths,
                 s.score, s.duration_s, s.created_at or time.time()),
            )

    @staticmethod
    def _to_session(r: sqlite3.Row) -> Session:
        return Session(
            mode=r["mode"], shots=r["shots"], hits=r["hits"],
            headshots=r["headshots"], kills=r["kills"], deaths=r["deaths"],
            score=r["score"], duration_s=r["duration_s"],
            created_at=r["created_at"],
        )

    def _rows(self, where: str = "", params: tuple = ()) -> list[Session]:
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            sql = ("SELECT * FROM sessions " + where +
                   " ORDER BY created_at DESC, id DESC")
            return [self._to_session(row) for row in c.execute(sql, params)]

    def recent(self, limit: int = 50) -> list[Session]:
        return self._rows("", ())[:limit]

    def by_mode(self, mode: str) -> list[Session]:
        return self._rows("WHERE mode = ?", (mode,))

    def all(self) -> list[Session]:
        return self._rows()


def aggregate(rows: list[Session]) -> dict:
    """把若干条记录汇总成一个概览字典（供历史面板顶部显示）。"""
    n = len(rows)
    t_shots = sum(r.shots for r in rows)
    t_hits = sum(r.hits for r in rows)
    t_hs = sum(r.headshots for r in rows)
    t_kills = sum(r.kills for r in rows)
    t_deaths = sum(r.deaths for r in rows)
    t_score = sum(r.score for r in rows)
    return {
        "sessions": n,
        "shots": t_shots,
        "hits": t_hits,
        "headshots": t_hs,
        "kills": t_kills,
        "deaths": t_deaths,
        "score": t_score,
        "accuracy": (t_hits / t_shots) if t_shots > 0 else None,
        "headshot_rate": (t_hs / t_shots) if t_shots > 0 else None,
        "kd": (t_kills / t_deaths) if t_deaths > 0
               else (float(t_kills) if t_kills > 0 else None),
    }
