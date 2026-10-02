"""回归测试：战绩历史面板（打开 / 返回 / 滚动夹紧 / 渲染不崩）。

直接跑：  python3 tests/test_history.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import main  # noqa: E402
import hud  # noqa: E402
import stats  # noqa: E402

PASS, FAIL = [], []


def _fresh_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="geom_aim_hist_")
    os.close(fd)
    os.unlink(path)
    os.environ["GEOM_AIM_STATS_DB"] = path
    return path


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def _seed(n: int):
    store = stats.LocalStatsStore(os.environ["GEOM_AIM_STATS_DB"])
    for i in range(n):
        store.record(stats.Session(
            mode="botz" if i % 2 == 0 else "match",
            shots=100 + i, hits=70 + i % 10, headshots=10 + i % 5,
            kills=i if i % 2 else 0, deaths=(i % 3) if i % 2 else 0,
            score=i * 5, duration_s=60.0 + i,
            created_at=1_700_000_000 + i * 100,
        ))


def test_open_history_from_title():
    _fresh_db()
    g = main.Game()
    assert g.state == "title"
    g.on_key(pygame.K_6)
    check("标题按 6 进入历史面板", g.state == "history", g.state)
    g.on_key(pygame.K_h)        # 历史里 H 也应返回（避免被全局 H→to_title 误伤）
    check("历史里按 H 返回标题", g.state == "title", g.state)


def test_history_escape_back():
    _fresh_db()
    g = main.Game()
    g.on_key(pygame.K_6)
    g.on_key(pygame.K_ESCAPE)
    check("历史里 ESC 返回标题", g.state == "title", g.state)


def test_history_draw_no_crash():
    _fresh_db()
    _seed(8)
    g = main.Game()
    g.state = "history"
    try:
        hud.draw_history(g.screen, g.renderer, g)
        ok = True
    except Exception as e:  # noqa: BLE001
        ok = False
        detail = repr(e)
    check("历史面板渲染不崩（有记录）", ok, locals().get("detail", ""))


def test_history_draw_empty_no_crash():
    _fresh_db()
    g = main.Game()
    g.state = "history"
    try:
        hud.draw_history(g.screen, g.renderer, g)
        ok = True
    except Exception as e:  # noqa: BLE001
        ok = False
        detail = repr(e)
    check("历史面板渲染不崩（无记录）", ok, locals().get("detail", ""))


def test_history_scroll_clamped():
    _fresh_db()
    _seed(40)
    g = main.Game()
    g.state = "history"
    g.history_scroll = 9999
    hud.draw_history(g.screen, g.renderer, g)
    rows = g.stats_store.recent(limit=200)
    check("滚动偏移被夹紧到合法范围",
          g.history_scroll <= len(rows),
          f"scroll={g.history_scroll} rows={len(rows)}")
    check("滚动偏移不为负", g.history_scroll >= 0, str(g.history_scroll))


def test_history_export_csv_key():
    import csv as _csv
    _fresh_db()
    _seed(5)
    g = main.Game()
    g.state = "history"
    g.on_key(pygame.K_e)
    path = g.exported_csv_path
    check("按 E 后记录导出路径", bool(path), str(path))
    check("导出文件存在", path is not None and os.path.exists(path), str(path))
    if path and os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            data = list(_csv.reader(f))
        check("表头 + 5 行战绩", len(data) == 6, str(len(data)))
        check("路径在成绩库同目录",
              os.path.dirname(path) == os.path.dirname(
                  os.environ["GEOM_AIM_STATS_DB"]), path)
        os.unlink(path)
    else:
        check("表头 + 5 行战绩", False, "no file")
        check("路径在成绩库同目录", False, "no file")


def run_tests():
    print("=== 战绩历史面板回归 ===")
    test_open_history_from_title(); print()
    test_history_escape_back(); print()
    test_history_draw_no_crash(); print()
    test_history_draw_empty_no_crash(); print()
    test_history_scroll_clamped(); print()
    test_history_export_csv_key(); print()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
