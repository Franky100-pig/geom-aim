"""TDD 测试：tools/user_count.py 用户数度量（纯离线，不碰网络）。

直接跑：  python3 tests/test_user_count.py

这个脚本存在的意义是决定「账号系统能不能启动」，所以它的口径错了会直接
误导决策。测的重点因此不是覆盖率，而是三件会改变结论的事：
汇总算得对不对、翻页的三种形状吃不吃得下、阈值判定在边界上是不是反的。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))          # 仓库根（对齐其它测试）
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "tools"))

import user_count  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def _rel(tag, *counts):
    return {"tag_name": tag, "published_at": "2026-01-02T03:04:05Z",
            "assets": [{"download_count": c} for c in counts]}


def test_sums_assets_across_a_release():
    rows, total = user_count.count_downloads(
        [_rel("v1.0", 5, 7, 0)], self_downloads=0)
    check("一个 release 的多个资产会相加", rows[0]["raw"] == 12, str(rows[0]["raw"]))
    check("总计等于净和", total == 12, str(total))


def test_self_downloads_are_subtracted_per_release():
    # 两个 release、每个减 1：这是「自己每个版本都下过一次」的真实形状。
    rows, total = user_count.count_downloads(
        [_rel("v1", 10), _rel("v2", 10)], self_downloads=1)
    check("每个 release 各减一次自己", total == 18, str(total))
    check("净额按 release 夹到 0，不出现负数",
          user_count.count_downloads([_rel("v0", 0, 0)], self_downloads=1)[1] == 0)


def test_a_single_release_does_not_lose_the_self_download():
    # 先汇总再减 1 会得到 19；逐个减才是 18。差别只有 1，但正好压在阈值上。
    _, total = user_count.count_downloads(
        [_rel("v1", 10), _rel("v2", 10)], self_downloads=1)
    check("逐个减而非汇总后减（否则会多算）", total == 18, str(total))


def test_missing_or_odd_fields_do_not_crash():
    rows, total = user_count.count_downloads(
        [{"tag_name": "v1"}, {"assets": None}, {"assets": [{}]},
         {"tag_name": "", "assets": [{"download_count": None}, {"download_count": "4"}]}],
        self_downloads=0)
    check("缺 assets / 缺 download_count / 字符串数字都能吃下",
          total == 4 and rows[0]["tag"] == "v1", f"total={total}")


def test_empty_and_none_inputs():
    check("空列表 → 0", user_count.count_downloads([], self_downloads=0)[1] == 0)
    check("None → 0", user_count.count_downloads(None, self_downloads=0)[1] == 0)


def test_flatten_pages_accepts_all_three_shapes():
    flat = user_count.flatten_pages([_rel("v1", 1)])
    check("单页 [{...}] 摊平", len(flat) == 1)

    paged = user_count.flatten_pages([[_rel("v1", 1)], [_rel("v2", 2)]])
    check("多页 [[{...}],[{...}]] 摊平", [r["tag_name"] for r in paged] == ["v1", "v2"])

    check("错误对象 {message:...} 当作空", user_count.flatten_pages({"message": "x"}) == [])
    check("页内混入非 dict 不会炸",
          len(user_count.flatten_pages([[{"tag_name": "v1"}, "垃圾"]])) == 1)


def test_verdict_is_strict_at_the_boundary():
    below, _ = user_count.verdict(19, threshold=20)
    at, _ = user_count.verdict(20, threshold=20)
    check("19 < 20 → 不动工", below is False)
    check("20 ≥ 20 → 该去核实真实用户数", at is True)
    # 这句措辞是刻意的：下载量只是上界，达到阈值不等于可以开工。
    _, line = user_count.verdict(20, threshold=20)
    check("达到阈值时措辞不承诺开工", "不是直接开工" in line, line)


def test_main_offline_end_to_end():
    releases = [_rel("v0.1", 8), _rel("v0.2", 9)]
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(releases, fh)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = user_count.main(["--file", path, "--json", "--self-downloads", "1"])
    os.unlink(path)

    payload = json.loads(buf.getvalue())
    check("main() 离线跑通且返回 0", rc == 0, f"rc={rc}")
    check("end-to-end 总数为 (8-1)+(9-1)=15", payload["total_net"] == 15,
          str(payload["total_net"]))
    check("未达阈值时 enough 为 False", payload["enough"] is False)
    check("json 里带上了口径（否则数字无法复核）",
          payload["self_downloads_per_release"] == 1
          and payload["threshold"] == user_count.THRESHOLD)


def test_no_release_is_reported_as_zero_not_as_success():
    # 仓库一个 release 都没有时，净下载量是 0 —— 不能因为「没数据」就放行。
    buf = io.StringIO()
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump([], fh)
    with contextlib.redirect_stdout(buf):
        user_count.main(["--file", path])
    os.unlink(path)
    out = buf.getvalue()
    check("无 release 时明确说「还没有任何 release」", "还没有任何 release" in out, out.strip())
    check("无 release 时结论是不动工", "继续不动工" in out)


if __name__ == "__main__":
    test_sums_assets_across_a_release()
    test_self_downloads_are_subtracted_per_release()
    test_a_single_release_does_not_lose_the_self_download()
    test_missing_or_odd_fields_do_not_crash()
    test_empty_and_none_inputs()
    test_flatten_pages_accepts_all_three_shapes()
    test_verdict_is_strict_at_the_boundary()
    test_main_offline_end_to_end()
    test_no_release_is_reported_as_zero_not_as_success()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        raise SystemExit(1)
